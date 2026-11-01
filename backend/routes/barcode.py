from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from barcode_service import is_isbn13, is_valid_gtin, lookup_enabled, lookup_product, normalize_code
from dependencies import get_db, role_required
from models import BarcodeProductCache, Inventory, Item, ItemBarcode, RoleEnum
from routes.auth import get_current_user
from routes.item import _ensure_barcode_free, _snapshot_item, _write_item_version, can_access_item
from schemas import BarcodeLookupResponse, BarcodeMatch, BarcodeProduct

router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(role_required(RoleEnum.admin))])


class BarcodeDebugRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    format: str | None = Field(default=None, max_length=64)
    force_refresh: bool = False


class BarcodeCorrectionRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    format: str | None = Field(default=None, max_length=64)


@router.get("/lookup", response_model=BarcodeLookupResponse)
def lookup_barcode(
    code: str = Query(..., min_length=1, max_length=256),
    inventory_id: int | None = Query(None, description="Limita le corrispondenze a un inventario"),
    external: bool = Query(True, description="Se nessun item corrisponde, interroga l'anagrafica esterna (EAN/UPC)"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    normalized = normalize_code(code)
    if not normalized:
        raise HTTPException(status_code=400, detail="Codice vuoto")

    query = (
        db.query(Item)
        .join(ItemBarcode, ItemBarcode.item_id == Item.id)
        .options(joinedload(Item.inventory))
        .filter(ItemBarcode.code == normalized)
    )
    if inventory_id is not None:
        query = query.filter(Item.inventory_id == inventory_id)

    matches = [
        BarcodeMatch(
            item_id=item.id,
            name=item.name,
            quantity=item.quantity,
            inventory_id=item.inventory_id,
            inventory_name=item.inventory.name if item.inventory else None,
            inventory_type=item.inventory.type if item.inventory else None,
        )
        for item in query.all()
        if can_access_item(user, item, action="view")
    ]

    product = None
    if not matches and external:
        cached = lookup_product(db, normalized)
        if cached is not None:
            product = BarcodeProduct(
                name=cached.name,
                brand=cached.brand,
                quantity_label=cached.quantity_label,
                image_url=cached.image_url,
                source=cached.source,
            )

    return BarcodeLookupResponse(code=normalized, matches=matches, product=product)


@admin_router.get("/codes")
def list_registered_barcodes(
    query: str = Query(default="", max_length=256),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ItemBarcode, Item, Inventory)
        .join(Item, Item.id == ItemBarcode.item_id)
        .join(Inventory, Inventory.id == Item.inventory_id)
    )
    if query.strip():
        needle = f"%{query.strip()}%"
        rows = rows.filter(or_(ItemBarcode.code.ilike(needle), Item.name.ilike(needle), Inventory.name.ilike(needle)))
    return [
        {
            "id": barcode.id,
            "code": barcode.code,
            "format": barcode.format,
            "item_id": item.id,
            "item_name": item.name,
            "inventory_id": inventory.id,
            "inventory_name": inventory.name,
            "data_mod": barcode.data_mod,
        }
        for barcode, item, inventory in rows.order_by(ItemBarcode.data_mod.desc(), ItemBarcode.id.desc()).limit(limit).all()
    ]


@admin_router.put("/codes/{barcode_id}")
def correct_registered_barcode(
    barcode_id: int,
    payload: BarcodeCorrectionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    barcode = db.query(ItemBarcode).options(joinedload(ItemBarcode.item).joinedload(Item.inventory)).filter(ItemBarcode.id == barcode_id).first()
    if barcode is None or barcode.item is None or barcode.item.inventory is None:
        raise HTTPException(status_code=404, detail="Codice barcode non trovato")

    item = barcode.item
    normalized = normalize_code(payload.code)
    if not normalized:
        raise HTTPException(status_code=400, detail="Codice vuoto")
    _ensure_barcode_free(db, normalized, item.inventory_id, exclude_item_id=item.id)
    duplicate = db.query(ItemBarcode).filter(
        ItemBarcode.item_id == item.id,
        ItemBarcode.code == normalized,
        ItemBarcode.id != barcode.id,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Questo codice è già associato allo stesso item")

    old_snapshot = _snapshot_item(item)
    old_codes = [entry.code for entry in item.barcodes]
    barcode.code = normalized
    barcode.format = payload.format
    barcode.user_mod = user.id
    item.user_mod = user.id
    db.flush()
    db.refresh(item)
    _write_item_version(
        db,
        item,
        "UPDATE",
        user,
        old_snapshot,
        extra_diff={"barcodes": {"from": old_codes, "to": [entry.code for entry in item.barcodes]}},
    )
    db.commit()
    db.refresh(barcode)
    return {"id": barcode.id, "code": barcode.code, "format": barcode.format, "item_id": item.id, "item_name": item.name}


@admin_router.get("/cache")
def list_barcode_cache(
    query: str = Query(default="", max_length=256),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    rows = db.query(BarcodeProductCache)
    if query.strip():
        needle = f"%{query.strip()}%"
        rows = rows.filter(or_(BarcodeProductCache.code.ilike(needle), BarcodeProductCache.name.ilike(needle), BarcodeProductCache.brand.ilike(needle)))
    return [
        {
            "code": row.code,
            "found": row.found,
            "name": row.name,
            "brand": row.brand,
            "quantity_label": row.quantity_label,
            "image_url": row.image_url,
            "source": row.source,
            "fetched_at": row.fetched_at,
        }
        for row in rows.order_by(BarcodeProductCache.fetched_at.desc()).limit(limit).all()
    ]


@admin_router.post("/debug")
def debug_barcode(payload: BarcodeDebugRequest, db: Session = Depends(get_db)):
    normalized = normalize_code(payload.code)
    if payload.force_refresh:
        stale_cache = db.get(BarcodeProductCache, normalized)
        if stale_cache is not None:
            db.delete(stale_cache)
            db.commit()

    linked_rows = (
        db.query(ItemBarcode, Item, Inventory)
        .join(Item, Item.id == ItemBarcode.item_id)
        .join(Inventory, Inventory.id == Item.inventory_id)
        .filter(ItemBarcode.code == normalized)
        .all()
    )
    source_checks: list[dict[str, str]] = []
    valid_gtin = is_valid_gtin(normalized)
    product = lookup_product(db, normalized, source_checks) if valid_gtin else None
    cached = db.get(BarcodeProductCache, normalized)
    return {
        "raw_code": payload.code,
        "normalized_code": normalized,
        "format": payload.format,
        "is_valid_gtin": valid_gtin,
        "is_isbn": is_isbn13(normalized),
        "lookup_enabled": lookup_enabled(),
        "source_checks": source_checks,
        "force_refresh": payload.force_refresh,
        "matches": [
            {
                "barcode_id": barcode.id,
                "item_id": item.id,
                "item_name": item.name,
                "inventory_id": inventory.id,
                "inventory_name": inventory.name,
            }
            for barcode, item, inventory in linked_rows
        ],
        "product": ({
            "name": product.name,
            "brand": product.brand,
            "quantity_label": product.quantity_label,
            "image_url": product.image_url,
            "source": product.source,
        } if product else None),
        "cache": ({
            "found": cached.found,
            "name": cached.name,
            "brand": cached.brand,
            "source": cached.source,
            "fetched_at": cached.fetched_at,
        } if cached else None),
        "checked_at": datetime.now(timezone.utc),
    }


@admin_router.delete("/cache")
def clear_barcode_cache(db: Session = Depends(get_db)):
    deleted = db.query(BarcodeProductCache).delete(synchronize_session=False)
    db.commit()
    return {"deleted": deleted}


@admin_router.delete("/cache/{code}")
def delete_barcode_cache_entry(code: str, db: Session = Depends(get_db)):
    normalized = normalize_code(code)
    row = db.get(BarcodeProductCache, normalized)
    if row is None:
        raise HTTPException(status_code=404, detail="Voce cache non trovata")
    db.delete(row)
    db.commit()
    return {"deleted": 1, "code": normalized}
