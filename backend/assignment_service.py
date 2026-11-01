from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session, object_session

from models import Item, ListAssignment, User
from schemas import AssignmentResponse, ItemAssignmentSummary

# Finestra entro cui togliere la spunta ripristina lo stock (stessa del merge delle versioni)
UNDO_WINDOW_SECONDS = 45


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _source_net(assignment: ListAssignment, pending: dict[int, int] | None) -> int | None:
    source = assignment.source_item
    if source is None:
        return None
    if pending is None:
        db = object_session(assignment)
        pending = pending_assigned_by_source(db, [source.id]) if db is not None else {}
    return int(source.quantity or 0) - pending.get(source.id, 0)


def build_assignment_summary(assignment: ListAssignment, pending: dict[int, int] | None = None) -> ItemAssignmentSummary:
    source = assignment.source_item
    inventory = source.inventory if source else None
    return ItemAssignmentSummary(
        id=assignment.id,
        list_checked=bool(assignment.list_item and (assignment.list_item.quantity or 0) >= 1),
        source_item_id=assignment.source_item_id,
        source_name=source.name if source else None,
        source_inventory_id=source.inventory_id if source else None,
        source_inventory_name=inventory.name if inventory else None,
        source_stock=source.quantity if source else None,
        source_net_qty=_source_net(assignment, pending),
        qty=assignment.qty,
    )


def build_assignment_response(assignment: ListAssignment) -> AssignmentResponse:
    source = assignment.source_item
    list_item = assignment.list_item
    source_inventory = source.inventory if source else None
    list_inventory = list_item.inventory if list_item else None
    return AssignmentResponse(
        id=assignment.id,
        list_item_id=assignment.list_item_id,
        list_item_name=list_item.name if list_item else None,
        list_id=list_item.inventory_id if list_item else None,
        list_name=list_inventory.name if list_inventory else None,
        list_checked=bool(list_item and (list_item.quantity or 0) >= 1),
        source_item_id=assignment.source_item_id,
        source_name=source.name if source else None,
        source_inventory_id=source.inventory_id if source else None,
        source_inventory_name=source_inventory.name if source_inventory else None,
        source_stock=source.quantity if source else None,
        source_net_qty=_source_net(assignment, None),
        qty=assignment.qty,
    )


def pending_assigned_by_source(db: Session, source_item_ids: Iterable[int]) -> dict[int, int]:
    """Somma delle quantita' assegnate in essere (righe di lista non spuntate) per item sorgente."""
    ids = list(source_item_ids)
    if not ids:
        return {}
    rows = (
        db.query(ListAssignment)
        .join(Item, Item.id == ListAssignment.list_item_id)
        .filter(ListAssignment.source_item_id.in_(ids), Item.quantity < 1)
        .all()
    )
    totals: dict[int, int] = {}
    for row in rows:
        totals[row.source_item_id] = totals.get(row.source_item_id, 0) + row.qty
    return totals


def apply_check_change(
    db: Session,
    list_item: Item,
    old_qty: int,
    new_qty: int,
    user: User,
    on_insufficient: str | None,
    can_edit_inventory: Callable[[User, Item], bool],
    write_version: Callable[[Session, Item, str, User, dict | None, bool], None],
    snapshot: Callable[[Item], dict],
) -> None:
    """Scarica lo stock alla spunta; ripristina se la spunta viene tolta entro la finestra di annullamento."""
    assignment = list_item.list_assignment
    if assignment is None:
        return
    was_checked = (old_qty or 0) >= 1
    is_checked = (new_qty or 0) >= 1
    if was_checked == is_checked:
        return

    source = assignment.source_item
    if source is None:
        return
    if not can_edit_inventory(user, source):
        raise HTTPException(status_code=403, detail="Accesso negato all'inventario di origine")

    if is_checked:
        recently_unchecked = (
            assignment.applied_at is not None
            and int(assignment.applied_qty or 0) == 0
            and _utc_now_naive() - assignment.applied_at <= timedelta(seconds=UNDO_WINDOW_SECONDS)
        )
        if recently_unchecked:
            assignment.applied_at = None
            assignment.applied_qty = None
            return

        requested = int(assignment.qty)
        available = int(source.quantity or 0)
        if available < requested:
            if on_insufficient != "zero":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "insufficient_stock",
                        "available": available,
                        "requested": requested,
                        "source_name": source.name,
                    },
                )
            deducted = available
        else:
            deducted = requested
        if deducted > 0:
            old_snapshot = snapshot(source)
            source.quantity = available - deducted
            source.user_mod = user.id
            write_version(db, source, "UPDATE", user, old_snapshot, False)
        assignment.applied_at = _utc_now_naive()
        assignment.applied_qty = deducted
        return

    applied_at = assignment.applied_at
    applied_qty = int(assignment.applied_qty or 0)
    within_window = (
        applied_at is not None
        and _utc_now_naive() - applied_at <= timedelta(seconds=UNDO_WINDOW_SECONDS)
    )
    if within_window and applied_qty > 0:
        old_snapshot = snapshot(source)
        source.quantity = int(source.quantity or 0) + applied_qty
        source.user_mod = user.id
        write_version(db, source, "UPDATE", user, old_snapshot, False)
        assignment.applied_at = None
        assignment.applied_qty = None
        return

    if within_window:
        assignment.applied_at = None
        assignment.applied_qty = None
    else:
        assignment.applied_at = _utc_now_naive()
        assignment.applied_qty = 0
