import json
from typing import Any, List, cast
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from models import User, Item, Inventory, ItemVersion, ItemBarcode
from assignment_service import apply_check_change, build_assignment_summary, pending_assigned_by_source
from dependencies import get_db
from schemas import ItemCreate, ItemUpdate, ItemDelete, ItemMetadataValueResponse, ItemResponse, ItemVersionResponse, VersionBulkDeleteRequest, ItemBarcodeCreate, ItemBarcodeResponse
from barcode_service import normalize_code
from routes.auth import get_current_user
from routes.inventory import can_access_inventory
from fastapi import status
from datetime import datetime, timezone, timedelta

router = APIRouter()
QUANTITY_MERGE_WINDOW_SECONDS = 45


def _utc_now_naive() -> datetime:
    # Usiamo UTC naive in modo coerente con i campi datetime senza timezone nel DB.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)

# Funzione per verificare se l'utente ha accesso a un item
def can_access_item(user: User, item: Item, action: str = "view") -> bool:
    if not item.inventory:
        return False
    return can_access_inventory(user, item.inventory, action)

# ---------------------------------------------------------------------------
# Helpers per la versioning degli item
# ---------------------------------------------------------------------------
def _snapshot_item(item: Item) -> dict:
    return {
        "name": item.name,
        "description": item.description,
        "quantity": item.quantity,
        "inventory_id": item.inventory_id,
    }

def _next_item_version_num(db: Session, item_id: int) -> int:
    last = db.query(func.max(ItemVersion.version_num)).filter(
        ItemVersion.item_id == item_id
    ).scalar()
    return (last or 0) + 1

def _write_item_version(
    db: Session,
    item: Item,
    operation: str,
    user: User,
    old_snapshot: dict[str, Any] | None = None,
    merge_quantity_updates: bool = True,
    extra_diff: dict[str, Any] | None = None,
) -> None:
    diff: dict = {}
    new_snapshot = None
    if old_snapshot and operation == "UPDATE":
        new_snapshot = _snapshot_item(item)
        for key, new_val in new_snapshot.items():
            old_val = old_snapshot.get(key)
            if old_val != new_val:
                diff[key] = {"from": old_val, "to": new_val}

        if extra_diff:
            diff.update(extra_diff)

        # Evita versioni vuote quando non cambia nulla
        if not diff:
            return

        # Accorpa aggiornamenti consecutivi di sola quantita in una sola versione
        # (stesso item, stesso utente, finestra temporale breve)
        if merge_quantity_updates and set(diff.keys()) == {"quantity"}:
            item_id = cast(int, item.id)
            last_version = (
                db.query(ItemVersion)
                .filter(ItemVersion.item_id == item_id)
                .order_by(ItemVersion.version_num.desc())
                .first()
            )

            if not last_version:
                last_changed_at = None
                last_operation = None
                last_changed_by_id = None
                last_diff_raw = None
            else:
                raw_changed_at = cast(datetime | None, last_version.changed_at)
                last_changed_at = _to_utc_naive(raw_changed_at) if raw_changed_at else None
                last_operation = cast(str, last_version.operation)
                last_changed_by_id = cast(int | None, last_version.changed_by_id)
                last_diff_raw = cast(str | None, last_version.diff)

            if (
                last_version
                and last_operation == "UPDATE"
                and last_changed_by_id == user.id
                and last_changed_at is not None
                and last_changed_at >= _utc_now_naive() - timedelta(seconds=QUANTITY_MERGE_WINDOW_SECONDS)
            ):
                try:
                    previous_diff = json.loads(last_diff_raw) if last_diff_raw else {}
                except Exception:
                    previous_diff = {}

                # Accorpa solo se anche la versione precedente era di sola quantita
                if set(previous_diff.keys()) == {"quantity"}:
                    qty_from = previous_diff.get("quantity", {}).get("from", old_snapshot.get("quantity"))
                    qty_to = new_snapshot.get("quantity")

                    # Se qty_from == qty_to, le modifiche si annullano: non registrare nulla
                    # MA solo se siamo ancora entro la finestra di merge (doppio check per sicurezza)
                    if qty_from == qty_to:
                        # Verifica ancora che siamo dentro la finestra (re-check per edge cases)
                        time_since_last = (_utc_now_naive() - last_changed_at).total_seconds()
                        if time_since_last <= QUANTITY_MERGE_WINDOW_SECONDS:
                            # Rimuovi la versione precedente dal db poiché è stata annullata
                            db.delete(last_version)
                            return
                        # Se siamo fuori della finestra, non cancellare: crea una nuova versione

                    setattr(last_version, "name", item.name)
                    setattr(last_version, "description", item.description)
                    setattr(last_version, "quantity", item.quantity)
                    setattr(last_version, "inventory_id", item.inventory_id)
                    setattr(last_version, "changed_at", _utc_now_naive())
                    setattr(last_version, "changed_by_username", user.username)
                    setattr(last_version, "diff", json.dumps({"quantity": {"from": qty_from, "to": qty_to}}))
                    return

    item_id = cast(int, item.id)
    inventory_id = cast(int, item.inventory_id)
    version = ItemVersion(
        item_id=item_id,
        inventory_id=inventory_id,
        name=item.name,
        description=item.description,
        quantity=item.quantity,
        version_num=_next_item_version_num(db, item_id),
        operation=operation,
        changed_at=_utc_now_naive(),
        changed_by_id=user.id,
        changed_by_username=user.username,
        diff=json.dumps(diff) if diff else None,
    )
    db.add(version)

def _dedupe_barcodes(payloads: List[ItemBarcodeCreate]) -> list[tuple[str, str | None]]:
    seen: dict[str, str | None] = {}
    for payload in payloads:
        code = normalize_code(payload.code)
        if code and code not in seen:
            seen[code] = payload.format
    return list(seen.items())

def _ensure_barcode_free(db: Session, code: str, inventory_id: int, exclude_item_id: int | None = None) -> None:
    """Un codice identifica un solo item per inventario: segnala 409 con l'item in conflitto."""
    query = (
        db.query(Item)
        .join(ItemBarcode, ItemBarcode.item_id == Item.id)
        .filter(ItemBarcode.code == code, Item.inventory_id == inventory_id)
    )
    if exclude_item_id is not None:
        query = query.filter(Item.id != exclude_item_id)
    other = query.first()
    if other:
        raise HTTPException(
            status_code=409,
            detail=f"Codice {code} gia' associato all'item '{other.name}' (id {other.id}) in questo inventario",
        )

def _assignment_fields(db: Session, item: Item) -> dict:
    if item.inventory is not None and item.inventory.type == "CHECKLIST":
        if item.list_assignment is None:
            return {}
        return {"assignment": build_assignment_summary(item.list_assignment)}
    assigned = pending_assigned_by_source(db, [cast(int, item.id)]).get(cast(int, item.id), 0)
    assignment_count = len(item.source_assignments)
    if not assigned and not assignment_count:
        return {}
    return {
        "assignment_count": assignment_count,
        "assigned_qty": assigned,
        "net_qty": cast(int, item.quantity or 0) - assigned,
    }

def _build_item_response(db: Session, item: Item) -> ItemResponse:
    current_version = db.query(func.max(ItemVersion.version_num)).filter(
        ItemVersion.item_id == item.id
    ).scalar() or 0
    return ItemResponse(
        id=cast(int, item.id),
        barcodes=[ItemBarcodeResponse.model_validate(b) for b in item.barcodes],
        name=cast(str, item.name),
        description=cast(str | None, item.description),
        quantity=cast(int, item.quantity),
        inventory_id=cast(int, item.inventory_id),
        data_ins=item.data_ins,
        data_mod=item.data_mod,
        user_ins=item.user_ins,
        user_mod=item.user_mod,
        username_ins=item.user_ins_rel.username if item.user_ins_rel else None,
        username_mod=item.user_mod_rel.username if item.user_mod_rel else None,
        metadata_values=[
            ItemMetadataValueResponse(
                **value.__dict__,
                definition_key=value.definition.key if value.definition else None,
                definition_label=value.definition.label if value.definition else None,
                field_type=value.definition.field_type if value.definition else None,
            )
            for value in item.metadata_values
        ],
        version_num=current_version,
        **_assignment_fields(db, item),
    )

#############################################################################
# Visualizzazione item
@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    item = db.query(Item).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item non trovato")
    if not can_access_item(user, item, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    return _build_item_response(db, item)

#############################################################################
# Creazione item
@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
def create_item(item: ItemCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    inventory = db.query(Inventory).filter(Inventory.id == item.inventory_id).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    new_barcodes = _dedupe_barcodes(item.barcodes)
    for code, _fmt in new_barcodes:
        _ensure_barcode_free(db, code, cast(int, inventory.id))
    db_item = Item(**item.model_dump(exclude={"barcodes"}))
    db_item.user_ins = user.id
    db_item.user_mod = user.id
    for code, fmt in new_barcodes:
        db_item.barcodes.append(ItemBarcode(code=code, format=fmt, user_ins=user.id, user_mod=user.id))
    db.add(db_item)
    db.flush()                                   # ottieni db_item.id senza commit
    _write_item_version(db, db_item, "CREATE", user)
    db.commit()
    db.refresh(db_item)
    inventory.data_mod = datetime.now(timezone.utc)
    inventory.user_mod = user.id
    db.commit()
    return _build_item_response(db, db_item)

#############################################################################
# Aggiornamento item
@router.patch("/{item_id}", response_model=ItemResponse)
def update_item(
    item_id: int,
    item_update: ItemUpdate,
    on_insufficient: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    item = db.query(Item).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item non trovato")
    if not can_access_item(user, item, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    old_snapshot = _snapshot_item(item)         # cattura stato precedente
    update_data = item_update.model_dump(exclude_unset=True)
    new_inventory_id = update_data.get("inventory_id")
    if new_inventory_id is not None and new_inventory_id != item.inventory_id:
        for barcode in item.barcodes:
            _ensure_barcode_free(db, cast(str, barcode.code), new_inventory_id, exclude_item_id=cast(int, item.id))
    for field, value in update_data.items():
        if field in ("quantity") and value is not None:
            if isinstance(value, (int, float)) and value < 0:
                raise HTTPException(status_code=400, detail=f"{field} non può essere negativo")
        setattr(item, field, value)
    item.user_mod = user.id
    if "quantity" in update_data:
        apply_check_change(
            db, item, cast(int, old_snapshot["quantity"]), cast(int, item.quantity), user, on_insufficient,
            lambda u, src: can_access_item(u, src, action="edit"),
            lambda d, i, op, u, snap, merge: _write_item_version(d, i, op, u, snap, merge),
            _snapshot_item,
        )
    _write_item_version(db, item, "UPDATE", user, old_snapshot)
    db.commit()
    db.refresh(item)
    item.inventory.data_mod = datetime.now(timezone.utc)
    item.inventory.user_mod = user.id
    db.commit()
    return _build_item_response(db, item)

#############################################################################
# Codici a barre / QR dell'item
@router.get("/{item_id}/barcodes", response_model=List[ItemBarcodeResponse])
def list_item_barcodes(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    item = db.query(Item).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item non trovato")
    if not can_access_item(user, item, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    return item.barcodes

@router.post("/{item_id}/barcodes", response_model=ItemBarcodeResponse, status_code=status.HTTP_201_CREATED)
def add_item_barcode(item_id: int, payload: ItemBarcodeCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    item = db.query(Item).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item non trovato")
    if not can_access_item(user, item, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    code = normalize_code(payload.code)
    if not code:
        raise HTTPException(status_code=400, detail="Codice vuoto")
    _ensure_barcode_free(db, code, cast(int, item.inventory_id), exclude_item_id=cast(int, item.id))
    if any(b.code == code for b in item.barcodes):
        raise HTTPException(status_code=409, detail=f"Codice {code} gia' associato a questo item")

    old_snapshot = _snapshot_item(item)
    old_codes = [b.code for b in item.barcodes]
    barcode = ItemBarcode(item_id=item.id, code=code, format=payload.format, user_ins=user.id, user_mod=user.id)
    db.add(barcode)
    db.flush()
    db.refresh(item)
    item.user_mod = user.id
    _write_item_version(
        db, item, "UPDATE", user, old_snapshot,
        extra_diff={"barcodes": {"from": old_codes, "to": [b.code for b in item.barcodes]}},
    )
    db.commit()
    db.refresh(barcode)
    return barcode

@router.delete("/{item_id}/barcodes/{barcode_id}")
def delete_item_barcode(item_id: int, barcode_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    item = db.query(Item).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item non trovato")
    if not can_access_item(user, item, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    barcode = db.query(ItemBarcode).filter(ItemBarcode.id == barcode_id, ItemBarcode.item_id == item_id).first()
    if not barcode:
        raise HTTPException(status_code=404, detail="Codice non trovato")

    old_snapshot = _snapshot_item(item)
    old_codes = [b.code for b in item.barcodes]
    db.delete(barcode)
    db.flush()
    db.refresh(item)
    item.user_mod = user.id
    _write_item_version(
        db, item, "UPDATE", user, old_snapshot,
        extra_diff={"barcodes": {"from": old_codes, "to": [b.code for b in item.barcodes]}},
    )
    db.commit()
    return {"detail": "Codice rimosso"}

#############################################################################
# Eliminazione item
@router.delete("/{item_id}")
def delete_item(item_id: int, delete: ItemDelete, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not delete.confirm:
        raise HTTPException(status_code=400, detail="Cancellazione non confermata")
    item = db.query(Item).get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item non trovato")
    if not can_access_item(user, item, action="delete"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    _write_item_version(db, item, "DELETE", user)   # registra prima della delete
    item.inventory.data_mod = datetime.now(timezone.utc)
    item.inventory.user_mod = user.id
    db.delete(item)
    db.commit()
    return {"detail": "Item eliminato"}

#############################################################################
# Cronologia versioni item
@router.get("/{item_id}/history", response_model=List[ItemVersionResponse])
def get_item_history(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Se l'item esiste ancora, verifica i permessi
    item = db.query(Item).get(item_id)
    if item:
        if not can_access_item(user, item, action="view"):
            raise HTTPException(status_code=403, detail="Accesso negato")
    else:
        # Se l'item è stato cancellato, prova a validare accesso tramite inventario d'origine
        latest = (
            db.query(ItemVersion)
            .filter(ItemVersion.item_id == item_id)
            .order_by(ItemVersion.version_num.desc())
            .first()
        )
        if latest:
            source_inventory = db.query(Inventory).filter(Inventory.id == latest.inventory_id).first()
            if source_inventory and not can_access_inventory(user, source_inventory, action="view"):
                raise HTTPException(status_code=403, detail="Accesso negato")
            # Se l'inventario non esiste più, limitiamo la visibilità agli admin
            if not source_inventory and user.role.name != "admin":
                raise HTTPException(status_code=403, detail="Accesso negato")

    versions = (
        db.query(ItemVersion)
        .filter(ItemVersion.item_id == item_id)
        .order_by(ItemVersion.version_num.asc())
        .all()
    )
    return versions

#############################################################################
# Rollback a una versione precedente
@router.post("/{item_id}/rollback/{version_num}", response_model=ItemResponse)
def rollback_item(
    item_id: int,
    version_num: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    target = db.query(ItemVersion).filter(
        ItemVersion.item_id == item_id,
        ItemVersion.version_num == version_num,
    ).first()
    if not target or cast(str, target.operation) == "DELETE":
        raise HTTPException(status_code=400, detail="Versione non valida per il rollback")

    item = db.query(Item).get(item_id)

    # Ripristino di item cancellato: ricreazione dal snapshot della versione
    if not item:
        parent_inventory = db.query(Inventory).filter(Inventory.id == target.inventory_id).first()
        if not parent_inventory:
            raise HTTPException(status_code=404, detail="Inventario origine non trovato: ripristina prima l'inventario")
        if not can_access_inventory(user, parent_inventory, action="edit"):
            raise HTTPException(status_code=403, detail="Accesso negato")

        restored_item = Item(
            id=item_id,
            name=target.name,
            description=target.description,
            quantity=target.quantity,
            inventory_id=target.inventory_id,
            user_ins=user.id,
            user_mod=user.id,
        )
        db.add(restored_item)
        db.flush()
        _write_item_version(db, restored_item, "CREATE", user)
        db.commit()
        db.refresh(restored_item)
        return _build_item_response(db, restored_item)

    if not can_access_item(user, item, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    old_snapshot = _snapshot_item(item)
    item.name = target.name
    item.description = target.description
    item.quantity = target.quantity
    item.user_mod = user.id
    _write_item_version(db, item, "UPDATE", user, old_snapshot, merge_quantity_updates=False)
    db.commit()
    db.refresh(item)
    return _build_item_response(db, item)

#############################################################################
# Pulizia cronologia versioni item (solo admin)
@router.delete("/{item_id}/history/{version_num}")
def delete_item_history_version(
    item_id: int,
    version_num: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Solo admin può cancellare versioni")

    deleted = (
        db.query(ItemVersion)
        .filter(ItemVersion.item_id == item_id, ItemVersion.version_num == version_num)
        .delete(synchronize_session=False)
    )
    db.commit()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Versione non trovata")
    return {"detail": "Versione eliminata", "deleted": deleted}


@router.post("/{item_id}/history/delete")
def delete_item_history_versions(
    item_id: int,
    payload: VersionBulkDeleteRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Solo admin può cancellare versioni")
    if not payload.version_nums:
        raise HTTPException(status_code=400, detail="Nessuna versione selezionata")

    deleted = (
        db.query(ItemVersion)
        .filter(ItemVersion.item_id == item_id, ItemVersion.version_num.in_(payload.version_nums))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"detail": "Pulizia cronologia completata", "deleted": deleted}