from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from dependencies import get_db
from models import (
    User,
    Inventory,
    Item,
    ItemMetadataValue,
    SharedInventory,
    Group,
    SharedInventoryGroup,
    RoleEnum,
    InventoryVersion,
    ItemVersion,
)
from assignment_service import build_assignment_summary, pending_assigned_by_source
from schemas import InventoryCreate, InventoryResponse, InventoryUpdate, ItemMetadataValueResponse, ItemBarcodeResponse, ItemResponse, UserResponse, InventoryResponseWithItemCount, InventoryVersionResponse, VersionBulkDeleteRequest
from routes.auth import get_current_user
from typing import Any, List, cast
import re
import json
from datetime import datetime, timezone

#router = APIRouter()
inventory_router = APIRouter() # INVENTORY_TYPE = "INVENTORY"
checklist_router = APIRouter() # INVENTORY_TYPE = "CHECKLIST"

# Funzione per verificare se l'utente ha accesso all'inventario
def can_access_inventory(user: User, inventory: Inventory, action: str = "view") -> bool:
    # Admin ha sempre accesso
    if user.role.name == RoleEnum.admin.value:
        return True

    owner_id = cast(int | None, inventory.owner_id)

    if action == "view":
        # Chiunque può vedere se è condiviso o è il proprietario
        if owner_id == user.id:
            return True
        if user.id in [s.user_id for s in inventory.shared_with_users]:
            return True
        user_group_ids = {assoc.group_id for assoc in user.group_associations}
        inventory_group_ids = {g.group_id for g in inventory.shared_with_groups}
        if user_group_ids & inventory_group_ids:
            return True
    elif action in ("edit", "delete"):
        # Moderatori possono modificare/eliminare solo se è proprio o condiviso con loro
        if user.role.name == RoleEnum.moderator.value:
            if owner_id == user.id:
                return True
            if user.id in [s.user_id for s in inventory.shared_with_users]:
                return True
            user_group_ids = {assoc.group_id for assoc in user.group_associations}
            inventory_group_ids = {g.group_id for g in inventory.shared_with_groups}
            if user_group_ids & inventory_group_ids:
                return True

    return False

#############################################################################
# Helper per versioning inventario
#############################################################################
def _snapshot_inventory(inv: Inventory) -> dict[str, Any]:
    return {
        "name": inv.name,
        "type": inv.type,
        "owner_id": inv.owner_id,
    }

def _next_inventory_version_num(db: Session, inventory_id: int) -> int:
    last = db.query(func.max(InventoryVersion.version_num)).filter(
        InventoryVersion.inventory_id == inventory_id
    ).scalar()
    return (last or 0) + 1

def _write_inventory_version(
    db: Session, inv: Inventory, operation: str, user: User, old_snapshot: dict[str, Any] | None = None
) -> None:
    diff: dict = {}
    if old_snapshot and operation == "UPDATE":
        new_snapshot = _snapshot_inventory(inv)
        for key, new_val in new_snapshot.items():
            old_val = old_snapshot.get(key)
            if old_val != new_val:
                diff[key] = {"from": old_val, "to": new_val}

    inventory_id = cast(int, inv.id)
    version = InventoryVersion(
        inventory_id=inventory_id,
        name=inv.name,
        type=inv.type,
        owner_id=inv.owner_id,
        owner_username=inv.owner.username if inv.owner else None,
        version_num=_next_inventory_version_num(db, inventory_id),
        operation=operation,
        changed_by_id=user.id,
        changed_by_username=user.username,
        diff=json.dumps(diff) if diff else None,
    )
    db.add(version)

def _build_inventory_response(db: Session, inv: Inventory) -> InventoryResponse:
    current_version = db.query(func.max(InventoryVersion.version_num)).filter(
        InventoryVersion.inventory_id == inv.id
    ).scalar() or 0
    resp = InventoryResponse.model_validate(inv)
    resp.version_num = current_version
    return resp

def _current_item_version_num(db: Session, item_id: int) -> int:
    return (
        db.query(func.max(ItemVersion.version_num))
        .filter(ItemVersion.item_id == item_id)
        .scalar()
        or 0
    )

def _get_item_version_map(db: Session, item_ids: list[int]) -> dict[int, int]:
    """Ottiene in batch l'ultimo numero di versione per una lista di id item (evita problema N+1)."""
    if not item_ids:
        return {}
    results = (
        db.query(ItemVersion.item_id, func.max(ItemVersion.version_num))
        .filter(ItemVersion.item_id.in_(item_ids))
        .group_by(ItemVersion.item_id)
        .all()
    )
    return {item_id: max_ver or 0 for item_id, max_ver in results}

#############################################################################
# Lista degli inventari visibili all'utente
def list_inventories_base(
    inventory_type: str, 
    filtro: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    query = db.query(Inventory).filter(Inventory.type == inventory_type)
    if filtro:
        query = query.options(
            joinedload(Inventory.items).joinedload(Item.metadata_values).joinedload(ItemMetadataValue.definition)
        )
    else:
        query = query.options(joinedload(Inventory.items))

    inventories = query.all()
    visible_inventories = [
        inv for inv in inventories if can_access_inventory(user, inv, action="view")
    ]

    def highlight_match(text: str, filtro: str) -> str:
        pattern = re.compile(re.escape(filtro), re.IGNORECASE)
        return pattern.sub(lambda m: f"**{m.group(0)}**", text)

    def resolve_metadata_search_text(metadata_value: ItemMetadataValue) -> tuple[str, str] | None:
        definition = metadata_value.definition
        if definition is None:
            return None

        if not cast(bool, definition.is_active):
            return None

        field_type = cast(str, definition.field_type)
        if field_type not in ("TEXT", "LIST"):
            return None

        raw_text = cast(str | None, metadata_value.value_text)
        if not raw_text:
            return None

        display_text = raw_text
        if field_type == "LIST":
            for entry in cast(list[Any], definition.list_options or []):
                if not isinstance(entry, dict):
                    continue
                entry_value = str(entry.get("value", "")).strip()
                entry_label = str(entry.get("label", "")).strip()
                if entry_value == raw_text:
                    display_text = entry_label or raw_text
                    break

        return raw_text, display_text

    # Pre-caricamento in batch delle versioni degli item per evitare query N+1
    all_item_ids = [item.id for inv in visible_inventories for item in inv.items]
    item_version_map = _get_item_version_map(db, all_item_ids)

    result = []
    filtro_lower = filtro.lower()
    for inv in visible_inventories:
        matching_items = []
        if filtro:
            matching_items = []
            for item in inv.items:
                name_match = filtro_lower in (item.name or "").lower()
                desc_match = filtro_lower in (item.description or "").lower() if item.description else False
                highlighted_metadata = []
                for metadata_value in item.metadata_values:
                    resolved_metadata_text = resolve_metadata_search_text(metadata_value)
                    if not resolved_metadata_text:
                        continue
                    raw_metadata_text, display_metadata_text = resolved_metadata_text
                    definition_label = metadata_value.definition.label or metadata_value.definition.key
                    metadata_text_match = (
                        filtro_lower in raw_metadata_text.lower()
                        or filtro_lower in display_metadata_text.lower()
                    )
                    if metadata_text_match:
                        highlighted_metadata.append({
                            "definition_label": definition_label,
                            "value_text": highlight_match(display_metadata_text, filtro) if metadata_text_match else display_metadata_text,
                        })

                metadata_match = len(highlighted_metadata) > 0

                if name_match or desc_match or metadata_match:
                    # Evidenzia la parte corrispondente nel nome e nella descrizione (case-insensitive)
                    name_highlight = (item.name or "")
                    desc_highlight = (item.description or "") if item.description else None
                    if name_match:
                        name_highlight = highlight_match(name_highlight, filtro)
                    if desc_match and desc_highlight is not None:
                        desc_highlight = highlight_match(desc_highlight, filtro)
                    matching_items.append({
                        **ItemResponse(
                            id=item.id,
                            barcodes=[ItemBarcodeResponse.model_validate(b) for b in item.barcodes],
                            name=item.name,
                            description=item.description,
                            quantity=item.quantity,
                            inventory_id=item.inventory_id,
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
                            version_num=item_version_map.get(item.id, 0),
                        ).model_dump(),
                        "highlighted": {
                            "name": name_highlight,
                            "description": desc_highlight,
                            "metadata_text": highlighted_metadata,
                        }
                    })
            if not matching_items:
                continue  # Skip inventories that do not match the filter

        result.append({
            **InventoryResponseWithItemCount(
                **_build_inventory_response(db, inv).model_dump(),
                item_count=len(inv.items)
            ).model_dump(),
            "matching_items": matching_items if filtro else None
        })

    return result

# Creazione inventario
def create_inventory_base(
    inventory_type: str, 
    inventory: InventoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    new_inventory = Inventory(name=inventory.name, owner_id=user.id, type=inventory_type)
    new_inventory.user_ins = user.id
    new_inventory.user_mod = user.id
    db.add(new_inventory)
    db.flush()  # ottieni new_inventory.id
    _write_inventory_version(db, new_inventory, "CREATE", user)
    db.commit()
    db.refresh(new_inventory)
    return _build_inventory_response(db, new_inventory)

# Aggiornamento inventario
def update_inventory_base(
    inventory_type: str, 
    inventory_id: int,
    update: InventoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    old_snapshot = _snapshot_inventory(inventory)
    setattr(inventory, "name", update.name)
    inventory.user_mod = user.id
    inventory.data_mod = datetime.now(timezone.utc)
    _write_inventory_version(db, inventory, "UPDATE", user, old_snapshot)
    db.commit()
    db.refresh(inventory)
    return _build_inventory_response(db, inventory)

# Eliminazione inventario
def delete_inventory_base(
    inventory_type: str, 
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="delete"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    _write_inventory_version(db, inventory, "DELETE", user)  # registra prima della delete
    db.delete(inventory)
    db.commit()
    return {"detail": "Inventario eliminato"}

def _list_item_assignment_fields(item: Item, assigned_map: dict[int, int]) -> dict:
    if item.list_assignment is not None:
        return {"assignment": build_assignment_summary(item.list_assignment, assigned_map)}
    assignment_count = len(item.source_assignments)
    assigned = assigned_map.get(item.id, 0)
    if assignment_count or assigned:
        return {
            "assignment_count": assignment_count,
            "assigned_qty": assigned,
            "net_qty": (item.quantity or 0) - assigned,
        }
    return {}

#############################################################################
# Recupero item dell'inventario
def list_items_base(
    inventory_type: str,
    inventory_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    inventory = db.query(Inventory).options(
        joinedload(Inventory.items).joinedload(Item.user_ins_rel),
        joinedload(Inventory.items).joinedload(Item.user_mod_rel),
        joinedload(Inventory.items).joinedload(Item.metadata_values).joinedload(ItemMetadataValue.definition),
        joinedload(Inventory.items).joinedload(Item.barcodes),
        joinedload(Inventory.items).joinedload(Item.list_assignment),
    ).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    item_ids = [item.id for item in inventory.items]
    item_version_map = _get_item_version_map(db, item_ids)
    if inventory.type == "CHECKLIST":
        assigned_map = pending_assigned_by_source(
            db, [i.list_assignment.source_item_id for i in inventory.items if i.list_assignment is not None]
        )
    else:
        assigned_map = pending_assigned_by_source(db, [i.id for i in inventory.items])
    return [
        ItemResponse(
            id=item.id,
            barcodes=[ItemBarcodeResponse.model_validate(b) for b in item.barcodes],
            name=item.name,
            description=item.description,
            quantity=item.quantity,
            inventory_id=item.inventory_id,
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
            version_num=item_version_map.get(item.id, 0),
            **_list_item_assignment_fields(item, assigned_map),
        )
        for item in inventory.items
    ]

# Contare gli item dell'inventario
def count_items_base(
    inventory_type: str,
    inventory_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    return len(inventory.items)

#############################################################################
# Condivisione inventario
def share_base(
    inventory_type: str,
    inventory_id: int,
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Utente da condividere non trovato")

    # Verifica condivisione diretta
    existing = db.query(SharedInventory).filter_by(user_id=target_user.id, inventory_id=inventory_id).first()
    if existing:
        return {"detail": "Inventario già condiviso direttamente con questo utente"}

    # Verifica condivisione tramite gruppo
    user_group_ids = [assoc.group_id for assoc in target_user.group_associations]
    group_shares = db.query(SharedInventoryGroup).filter(
        SharedInventoryGroup.inventory_id == inventory_id,
        SharedInventoryGroup.group_id.in_(user_group_ids)
    ).first()
    if group_shares:
        return {"detail": "Inventario già accessibile tramite gruppo dell'utente"}

    shared = SharedInventory(user_id=target_user.id, inventory_id=inventory_id)
    db.add(shared)
    db.commit()
    return {"detail": f"Inventario condiviso con {target_user.username}"}

# Revoca condivisione inventario
def unshare_base(
    inventory_type: str,
    inventory_id: int,
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    shared = db.query(SharedInventory).filter_by(user_id=target_user.id, inventory_id=inventory_id).first()
    if not shared:
        raise HTTPException(status_code=404, detail="Condivisione non trovata")

    db.delete(shared)
    db.commit()
    return {"detail": f"Condivisione revocata per {username}"}

# Lista utenti con cui è condiviso un inventario
def list_shares_base(
    inventory_type: str,
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    return [
        db.query(User).get(share.user_id)
        for share in inventory.shared_with_users
    ]

#############################################################################
# Condivisione con gruppo
def share_with_group_base(
    inventory_type: str,
    inventory_id: int,
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    group = db.query(Group).get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")

    existing = db.query(SharedInventoryGroup).filter_by(group_id=group_id, inventory_id=inventory_id).first()
    if existing:
        return {"detail": "Inventario già condiviso con questo gruppo"}

    shared = SharedInventoryGroup(group_id=group_id, inventory_id=inventory_id)
    db.add(shared)
    db.commit()
    return {"detail": f"Inventario condiviso con il gruppo '{group.name}'"}

# Revoca condivisione da gruppo
def unshare_from_group_base(
    inventory_type: str,
    inventory_id: int,
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    shared = db.query(SharedInventoryGroup).filter_by(group_id=group_id, inventory_id=inventory_id).first()
    if not shared:
        raise HTTPException(status_code=404, detail="Condivisione non trovata")

    db.delete(shared)
    db.commit()
    return {"detail": "Condivisione con gruppo revocata"}

# Lista gruppi con cui è condiviso un inventario
def list_group_shares_base(
    inventory_type: str,
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    return [share.group.name for share in inventory.shared_with_groups]

#############################################################################
# Elencare tutti gli utenti che hanno accesso a un inventario, con tipo di accesso e modalità
def list_access_details_base(
    inventory_type: str,
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    access_details = []

    # Utente proprietario
    owner = db.query(User).get(inventory.owner_id)
    if owner is not None:
        access_details.append({
            "username": owner.username,
            "access": "edit",
            "via": "owner",
            "group": None
        })

    # Amministratori
    admins = db.query(User).filter(User.role.has(name=RoleEnum.admin.value)).all()
    for admin in admins:
        if cast(int | None, admin.id) != cast(int | None, inventory.owner_id):
            access_details.append({
                "username": admin.username,
                "access": "edit",
                "via": "admin",
                "group": None
            })

    # Utenti condivisione diretta
    for share in inventory.shared_with_users:
        shared_user = db.query(User).get(share.user_id)
        if shared_user is None or shared_user.role is None:
            continue
        access = "edit" if shared_user.role.name in (RoleEnum.admin.value, RoleEnum.moderator.value) else "view"
        access_details.append({
            "username": shared_user.username,
            "access": access,
            "via": "share",
            "group": None
        })

    # Utenti condivisione tramite gruppo
    for shared_group in inventory.shared_with_groups:
        group = db.query(Group).get(shared_group.group_id)
        if group is None:
            continue
        for assoc in group.user_associations:
            access = "edit" if assoc.user.role.name in (RoleEnum.admin.value, RoleEnum.moderator.value) else "view"
            access_details.append({
                "username": assoc.user.username,
                "access": access,
                "via": "group",
                "group": group.name
            })

    return access_details

#############################################################################
# Contare gli utenti che possono accedere all’inventario, raggruppati per accesso
def count_access_by_type_base(
    inventory_type: str,
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    access_by_user = {}

    # Owner
    owner = db.query(User).get(inventory.owner_id)
    if owner is not None:
        access_by_user[owner.username] = "edit"

    # Admin (aggiunti solo se non già presenti)
    admins = db.query(User).filter(User.role.has(name=RoleEnum.admin.value)).all()
    for admin in admins:
        if admin.username not in access_by_user:
            access_by_user[admin.username] = "admin"

    # Dirette
    for share in inventory.shared_with_users:
        shared_user = db.query(User).get(share.user_id)
        if shared_user is None or shared_user.role is None:
            continue
        access = "edit" if shared_user.role.name in (RoleEnum.admin.value, RoleEnum.moderator.value) else "view"
        access_by_user[shared_user.username] = access

    # Gruppi
    for shared_group in inventory.shared_with_groups:
        group = db.query(Group).get(shared_group.group_id)
        if group is None:
            continue
        for assoc in group.user_associations:
            access = "edit" if assoc.user.role.name in (RoleEnum.admin.value, RoleEnum.moderator.value) else "view"
            # Se già presente come 'edit' non sovrascrivere
            if assoc.user.username not in access_by_user or access_by_user[assoc.user.username] != "edit":
                access_by_user[assoc.user.username] = access

    # Conta
    view_count = sum(1 for access in access_by_user.values() if access == "view")
    edit_count = sum(1 for access in access_by_user.values() if access == "edit")
    admin_count = sum(1 for access in access_by_user.values() if access == "admin")

    return {"view": view_count, "edit": edit_count, "admin": admin_count}

def get_by_id_base(
    inventory_type: str,
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    inventory = db.query(Inventory).options(joinedload(Inventory.items)).filter_by(id=inventory_id, type=inventory_type).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    return InventoryResponseWithItemCount(
        **_build_inventory_response(db, inventory).model_dump(),
        item_count=len(inventory.items)
    )

#############################################################################
#############################################################################
#############################################################################
#############################################################################

#############################################################################
# Lista degli inventari visibili all'utente
@inventory_router.get("/", response_model=List[dict])
def list_inventories(
    filtro: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return list_inventories_base(
        inventory_type="INVENTORY",
        filtro=filtro,
        db=db,
        user=user
    )

# Lista delle checklist visibili all'utente
@checklist_router.get("/", response_model=List[dict])
def list_checklists(
    filtro: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return list_inventories_base(
        inventory_type="CHECKLIST",
        filtro=filtro,
        db=db,
        user=user
    )

#############################################################################
# Creazione inventario
@inventory_router.post("/", response_model=InventoryResponse)
def create_inventory(
    inventory: InventoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return create_inventory_base(
        inventory_type="INVENTORY",
        inventory=inventory,
        db=db,
        user=user
    )
# Creazione checklist
@checklist_router.post("/", response_model=InventoryResponse)
def create_checklist(
    inventory: InventoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return create_inventory_base(
        inventory_type="CHECKLIST",
        inventory=inventory,
        db=db,
        user=user
    )

#############################################################################
# Aggiornamento inventario
@inventory_router.patch("/{inventory_id}", response_model=InventoryResponse)
def update_inventory(
    inventory_id: int,
    update: InventoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return update_inventory_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        update=update,
        db=db,
        user=user
    )
# Aggiornamento checklist
@checklist_router.patch("/{inventory_id}", response_model=InventoryResponse)
def update_checklist(
    inventory_id: int,
    update: InventoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return update_inventory_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        update=update,
        db=db,
        user=user
    )

#############################################################################
# Eliminazione inventario
@inventory_router.delete("/{inventory_id}")
def delete_inventory(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return delete_inventory_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        db=db,
        user=user
    )
# Eliminazione checklist
@checklist_router.delete("/{inventory_id}")
def delete_checklist(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return delete_inventory_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        db=db,
        user=user
    )

#############################################################################
# Recupero item dell'inventario
@inventory_router.get("/item/{inventory_id}/", response_model=List[ItemResponse])
def list_items(
    inventory_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    return list_items_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        db=db,
        user=user
    )
# Recupero item della checklist
@checklist_router.get("/item/{inventory_id}/", response_model=List[ItemResponse])
def list_checklist_items(
    inventory_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    return list_items_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        db=db,
        user=user
    )

#############################################################################
# Contare gli item dell'inventario
@inventory_router.get("/count/{inventory_id}", response_model=int)
def count_inventory_items(
    inventory_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    return count_items_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        db=db,
        user=user
    )
# Contare gli item della checklist
@checklist_router.get("/count/{inventory_id}", response_model=int)
def count_checklist_items(
    inventory_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    return count_items_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        db=db,
        user=user
    )

#############################################################################
# Condivisione inventario
@inventory_router.post("/share/{inventory_id}/{username}")
def share_inventory(
    inventory_id: int,
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return share_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        username=username,
        db=db,
        user=user
    )
# Condivisione checklist
@checklist_router.post("/share/{inventory_id}/{username}")
def share_checklist(
    inventory_id: int,
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return share_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        username=username,
        db=db,
        user=user
    )

#############################################################################
# Revoca condivisione inventario
@inventory_router.delete("/share/{inventory_id}/{username}")
def unshare_inventory(
    inventory_id: int,
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return unshare_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        username=username,
        db=db,
        user=user
    )
# Revoca condivisione checklist
@checklist_router.delete("/share/{inventory_id}/{username}")
def unshare_checklist(
    inventory_id: int,
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return unshare_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        username=username,
        db=db,
        user=user
    )

#############################################################################
# Lista utenti con cui è condiviso un inventario
@inventory_router.get("/share/{inventory_id}", response_model=List[UserResponse])
def list_inventory_shares(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return list_shares_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        db=db,
        user=user
    )
# Lista utenti con cui è condivisa una checklist
@checklist_router.get("/share/{inventory_id}", response_model=List[UserResponse])
def list_checklist_shares(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return list_shares_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        db=db,
        user=user
    )

#############################################################################
# Condivisione con gruppo
@inventory_router.post("/share_group/{inventory_id}/{group_id}")
def share_inventory_with_group(
    inventory_id: int,
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return share_with_group_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        group_id=group_id,
        db=db,
        user=user
    )
# Condivisione checklist con gruppo
@checklist_router.post("/share_group/{inventory_id}/{group_id}")
def share_checklist_with_group(
    inventory_id: int,
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return share_with_group_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        group_id=group_id,
        db=db,
        user=user
    )
#############################################################################
# Revoca condivisione inventario da gruppo
@inventory_router.delete("/share_group/{inventory_id}/{group_id}")
def unshare_inventory_from_group(
    inventory_id: int,
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return unshare_from_group_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        group_id=group_id,
        db=db,
        user=user
    )
# Revoca condivisione checklist da gruppo
@checklist_router.delete("/share_group/{inventory_id}/{group_id}")
def unshare_checklist_from_group(
    inventory_id: int,
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return unshare_from_group_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        group_id=group_id,
        db=db,
        user=user
    )
#############################################################################
# Lista gruppi con cui è condiviso un inventario
@inventory_router.get("/share_group/{inventory_id}", response_model=List[str])
def list_inventory_group_shares(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return list_group_shares_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        db=db,
        user=user
    )
# Lista gruppi con cui è condivisa una checklist
@checklist_router.get("/share_group/{inventory_id}", response_model=List[str])
def list_checklist_group_shares(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return list_group_shares_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        db=db,
        user=user
    )

#############################################################################
# Elencare tutti gli utenti che hanno accesso a un inventario, con tipo di accesso e modalità
@inventory_router.get("/access_details/{inventory_id}", response_model=List[dict])
def list_inventory_access_details(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return list_access_details_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        db=db,
        user=user
    )
# Elencare tutti gli utenti che hanno accesso a una checklist, con tipo di accesso e modalità
@checklist_router.get("/access_details/{inventory_id}", response_model=List[dict])
def list_checklist_access_details(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return list_access_details_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        db=db,
        user=user
    )

#############################################################################
# Contare gli utenti che possono accedere all’inventario, raggruppati per accesso
@inventory_router.get("/access_count/{inventory_id}", response_model=dict)
def count_inventory_access_by_type(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return count_access_by_type_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        db=db,
        user=user
    )
# Contare gli utenti che possono accedere alla checklist, raggruppati per accesso
@checklist_router.get("/access_count/{inventory_id}", response_model=dict)
def count_checklist_access_by_type(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return count_access_by_type_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        db=db,
        user=user
    )

#############################################################################
# Recupero inventario per ID
@inventory_router.get("/{inventory_id}", response_model=InventoryResponseWithItemCount)
def get_inventory_by_id(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return get_by_id_base(
        inventory_type="INVENTORY",
        inventory_id=inventory_id,
        db=db,
        user=user
    )
# Recupero checklist per ID
@checklist_router.get("/{inventory_id}", response_model=InventoryResponseWithItemCount)
def get_checklist_by_id(
    inventory_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    return get_by_id_base(
        inventory_type="CHECKLIST",
        inventory_id=inventory_id,
        db=db,
        user=user
    )

#############################################################################
# Cronologia versioni inventario
@inventory_router.get("/{inventory_id}/history", response_model=List[InventoryVersionResponse])
def get_inventory_history(inventory_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Se l'inventario esiste ancora, verifica i permessi
    inv = db.query(Inventory).filter_by(id=inventory_id, type="INVENTORY").first()
    if inv:
        if not can_access_inventory(user, inv, action="view"):
            raise HTTPException(status_code=403, detail="Accesso negato")
    else:
        latest = (
            db.query(InventoryVersion)
            .filter(InventoryVersion.inventory_id == inventory_id)
            .order_by(InventoryVersion.version_num.desc())
            .first()
        )
        if latest and user.role.name != "admin" and latest.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Accesso negato")

    versions = (
        db.query(InventoryVersion)
        .filter(InventoryVersion.inventory_id == inventory_id)
        .order_by(InventoryVersion.version_num.asc())
        .all()
    )
    return versions

# Cronologia versioni checklist
@checklist_router.get("/{inventory_id}/history", response_model=List[InventoryVersionResponse])
def get_checklist_history(inventory_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    inv = db.query(Inventory).filter_by(id=inventory_id, type="CHECKLIST").first()
    if inv:
        if not can_access_inventory(user, inv, action="view"):
            raise HTTPException(status_code=403, detail="Accesso negato")
    else:
        latest = (
            db.query(InventoryVersion)
            .filter(InventoryVersion.inventory_id == inventory_id)
            .order_by(InventoryVersion.version_num.desc())
            .first()
        )
        if latest and user.role.name != "admin" and latest.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Accesso negato")

    versions = (
        db.query(InventoryVersion)
        .filter(InventoryVersion.inventory_id == inventory_id)
        .order_by(InventoryVersion.version_num.asc())
        .all()
    )
    return versions

#############################################################################
# Rollback a una versione precedente
@inventory_router.post("/{inventory_id}/rollback/{version_num}", response_model=InventoryResponse)
def rollback_inventory(
    inventory_id: int,
    version_num: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    target = db.query(InventoryVersion).filter(
        InventoryVersion.inventory_id == inventory_id,
        InventoryVersion.version_num == version_num,
    ).first()
    if target is None or cast(str, target.operation) == "DELETE":
        raise HTTPException(status_code=400, detail="Versione non valida per il rollback")

    inv = db.query(Inventory).filter_by(id=inventory_id, type="INVENTORY").first()

    # Ripristino di inventario cancellato
    if not inv:
        if cast(str, target.type) != "INVENTORY":
            raise HTTPException(status_code=400, detail="Versione non compatibile")
        if user.role.name == "viewer":
            raise HTTPException(status_code=403, detail="Accesso negato")
        if user.role.name != "admin" and target.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Accesso negato")

        restored = Inventory(
            id=inventory_id,
            name=target.name,
            type="INVENTORY",
            owner_id=target.owner_id or user.id,
            user_ins=user.id,
            user_mod=user.id,
            data_mod=datetime.now(timezone.utc),
        )
        db.add(restored)
        db.flush()
        _write_inventory_version(db, restored, "CREATE", user)
        db.commit()
        db.refresh(restored)
        return _build_inventory_response(db, restored)

    if not can_access_inventory(user, inv, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    old_snapshot = _snapshot_inventory(inv)
    setattr(inv, "name", cast(str, target.name))
    inv.user_mod = user.id
    inv.data_mod = datetime.now(timezone.utc)
    _write_inventory_version(db, inv, "UPDATE", user, old_snapshot)
    db.commit()
    db.refresh(inv)
    return _build_inventory_response(db, inv)

# Rollback checklist
@checklist_router.post("/{inventory_id}/rollback/{version_num}", response_model=InventoryResponse)
def rollback_checklist(
    inventory_id: int,
    version_num: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    target = db.query(InventoryVersion).filter(
        InventoryVersion.inventory_id == inventory_id,
        InventoryVersion.version_num == version_num,
    ).first()
    if target is None or cast(str, target.operation) == "DELETE":
        raise HTTPException(status_code=400, detail="Versione non valida per il rollback")

    inv = db.query(Inventory).filter_by(id=inventory_id, type="CHECKLIST").first()

    # Ripristino di checklist cancellata
    if not inv:
        if cast(str, target.type) != "CHECKLIST":
            raise HTTPException(status_code=400, detail="Versione non compatibile")
        if user.role.name == "viewer":
            raise HTTPException(status_code=403, detail="Accesso negato")
        if user.role.name != "admin" and target.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Accesso negato")

        restored = Inventory(
            id=inventory_id,
            name=target.name,
            type="CHECKLIST",
            owner_id=target.owner_id or user.id,
            user_ins=user.id,
            user_mod=user.id,
            data_mod=datetime.now(timezone.utc),
        )
        db.add(restored)
        db.flush()
        _write_inventory_version(db, restored, "CREATE", user)
        db.commit()
        db.refresh(restored)
        return _build_inventory_response(db, restored)

    if not can_access_inventory(user, inv, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    old_snapshot = _snapshot_inventory(inv)
    setattr(inv, "name", cast(str, target.name))
    inv.user_mod = user.id
    inv.data_mod = datetime.now(timezone.utc)
    _write_inventory_version(db, inv, "UPDATE", user, old_snapshot)
    db.commit()
    db.refresh(inv)
    return _build_inventory_response(db, inv)


#############################################################################
# Pulizia cronologia versioni inventario/checklist (solo admin)
@inventory_router.delete("/{inventory_id}/history/{version_num}")
def delete_inventory_history_version(
    inventory_id: int,
    version_num: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Solo admin può cancellare versioni")

    deleted = (
        db.query(InventoryVersion)
        .filter(InventoryVersion.inventory_id == inventory_id, InventoryVersion.version_num == version_num, InventoryVersion.type == "INVENTORY")
        .delete(synchronize_session=False)
    )
    db.commit()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Versione non trovata")
    return {"detail": "Versione eliminata", "deleted": deleted}


@inventory_router.post("/{inventory_id}/history/delete")
def delete_inventory_history_versions(
    inventory_id: int,
    payload: VersionBulkDeleteRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Solo admin può cancellare versioni")
    if not payload.version_nums:
        raise HTTPException(status_code=400, detail="Nessuna versione selezionata")

    deleted = (
        db.query(InventoryVersion)
        .filter(
            InventoryVersion.inventory_id == inventory_id,
            InventoryVersion.type == "INVENTORY",
            InventoryVersion.version_num.in_(payload.version_nums),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"detail": "Pulizia cronologia completata", "deleted": deleted}


@checklist_router.delete("/{inventory_id}/history/{version_num}")
def delete_checklist_history_version(
    inventory_id: int,
    version_num: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Solo admin può cancellare versioni")

    deleted = (
        db.query(InventoryVersion)
        .filter(InventoryVersion.inventory_id == inventory_id, InventoryVersion.version_num == version_num, InventoryVersion.type == "CHECKLIST")
        .delete(synchronize_session=False)
    )
    db.commit()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Versione non trovata")
    return {"detail": "Versione eliminata", "deleted": deleted}


@checklist_router.post("/{inventory_id}/history/delete")
def delete_checklist_history_versions(
    inventory_id: int,
    payload: VersionBulkDeleteRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Solo admin può cancellare versioni")
    if not payload.version_nums:
        raise HTTPException(status_code=400, detail="Nessuna versione selezionata")

    deleted = (
        db.query(InventoryVersion)
        .filter(
            InventoryVersion.inventory_id == inventory_id,
            InventoryVersion.type == "CHECKLIST",
            InventoryVersion.version_num.in_(payload.version_nums),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"detail": "Pulizia cronologia completata", "deleted": deleted}
