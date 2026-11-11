"""Personal event preferences, with modification access checked at delivery time."""

from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, joinedload

from models import Inventory, Item, ListAssignment, Notification, NotificationEvent, NotificationPreference, User
from notification_contracts import (
    InventoryUpdatedData, ItemQuantityChangedData, ItemUpdatedData, notification_event_adapter,
)
from notification_outbox import enqueue_event, utcnow
from quantity_changes import QUANTITY_MERGE_WINDOW_SECONDS


def default_in_app(event_type: str) -> bool:
    return False


def can_receive(user: User, inventory: Inventory) -> bool:
    from routes.inventory import can_access_inventory

    return bool(
        not user.is_blocked and user.role is not None
        and can_access_inventory(user, inventory, action="edit")
    )


def event_inventory(db: Session, record: NotificationEvent) -> Inventory | None:
    data = notification_event_adapter.validate_python(record.payload)
    inventory = db.get(Inventory, data.inventory_id)
    if inventory is not None and inventory.data_ins > record.created_at:
        return None
    if (inventory is not None and isinstance(data, (ItemQuantityChangedData, ItemUpdatedData))
            and not (isinstance(data, ItemUpdatedData) and data.operation == "deleted")):
        item = db.get(Item, data.item_id)
        if item is None or item.inventory_id != inventory.id or item.data_ins > record.created_at:
            return None
    return inventory


def remove_resource_events(
    db: Session, *, inventory_id: int | None = None, item_id: int | None = None,
) -> None:
    if inventory_id is not None:
        condition = NotificationEvent.payload["inventory_id"].as_integer() == inventory_id
    elif item_id is not None:
        condition = NotificationEvent.payload["item_id"].as_integer() == item_id
    else:
        raise ValueError("A resource ID is required")
    # JSON resource IDs have no FK; remove their events before SQLite can reuse IDs.
    db.execute(delete(NotificationEvent).where(condition))


def emit_item_updated(db: Session, item: Item, changed_fields: list[str], actor_id: int) -> None:
    fields = sorted(set(changed_fields) - {"quantity"})
    if fields:
        enqueue_event(db, ItemUpdatedData(
            inventory_id=item.inventory_id, item_id=item.id, changed_fields=fields,
            details={field: getattr(item, field) for field in fields if field in {"name", "description", "priority", "inventory_id"}},
        ), actor_id=actor_id)


def emit_item_created(db: Session, item: Item, actor_id: int) -> None:
    enqueue_event(db, ItemUpdatedData(
        inventory_id=item.inventory_id, item_id=item.id, changed_fields=["name"],
        operation="created", quantity=item.quantity,
        details={"name": item.name, "description": item.description},
    ), actor_id=actor_id)


def emit_item_deleted(db: Session, item: Item, actor_id: int) -> None:
    enqueue_event(db, ItemUpdatedData(
        inventory_id=item.inventory_id, changed_fields=["name"],
        operation="deleted", details={"name": item.name},
    ), actor_id=actor_id)


def emit_inventory_updated(
    db: Session, inventory: Inventory, changed_fields: list[str], actor_id: int,
) -> None:
    if changed_fields:
        enqueue_event(db, InventoryUpdatedData(
            inventory_id=inventory.id, changed_fields=sorted(set(changed_fields)),
            details={"name": inventory.name} if "name" in changed_fields else {},
        ), actor_id=actor_id)


def emit_removed_item_links(db: Session, item_ids: list[int], actor_id: int) -> None:
    """Cascaded link removal changes surviving items in other containers too."""
    removed = set(item_ids)
    changed: dict[int, set[str]] = {}
    for assignment in db.scalars(select(ListAssignment).where(or_(
        ListAssignment.list_item_id.in_(item_ids), ListAssignment.source_item_id.in_(item_ids),
    ))):
        if assignment.list_item_id not in removed:
            changed.setdefault(assignment.list_item_id, set()).add("assignment")
        if assignment.source_item_id not in removed:
            changed.setdefault(assignment.source_item_id, set()).add("assignments")
    for item_id, fields in changed.items():
        item = db.get(Item, item_id)
        if item is not None:
            emit_item_updated(db, item, sorted(fields), actor_id)


def emit_item_change(
    db: Session, item: Item, previous: dict, actor_id: int, *,
    now: datetime | None = None, merge_previous_at: datetime | None = None,
) -> None:
    old = previous.get("quantity") or 0
    new = item.quantity or 0
    if old == new:
        return
    if db.get(Inventory, item.inventory_id) is None:
        return
    current = now or utcnow()
    # Merge only a contiguous sequence by the same actor that is still unclaimed.
    pending = db.scalar(select(NotificationEvent).where(
        NotificationEvent.status == "pending",
        NotificationEvent.attempts == 0,
        NotificationEvent.actor_id == actor_id,
        NotificationEvent.payload["event_type"].as_string() == "item_quantity_changed",
        NotificationEvent.payload["item_id"].as_integer() == item.id,
        NotificationEvent.payload["inventory_id"].as_integer() == item.inventory_id,
        NotificationEvent.payload["quantity"].as_integer() == old,
        NotificationEvent.available_at > current,
    ).order_by(NotificationEvent.id.desc()).limit(1).with_for_update())
    initial = pending.payload["previous_quantity"] if pending is not None else old
    if initial == new:
        if pending is not None:
            db.delete(pending)
        return
    data = ItemQuantityChangedData(
        inventory_id=item.inventory_id, item_id=item.id, previous_quantity=initial, quantity=new,
        action_at=current.isoformat(),
    )
    if pending is None:
        pending = enqueue_event(db, data, actor_id=actor_id, now=current)
    else:
        pending.payload = data.model_dump(mode="json")
    pending.available_at = current + timedelta(seconds=QUANTITY_MERGE_WINDOW_SECONDS)


def event_recipients(db: Session, record: NotificationEvent) -> set[int]:
    inventory = event_inventory(db, record)
    if inventory is None:
        return set()
    users = db.scalars(select(User).options(
        joinedload(User.role), joinedload(User.group_associations),
    )).unique()
    return {user.id for user in users if can_receive(user, inventory)}


def evaluate_event(db: Session, record: NotificationEvent) -> None:
    data = notification_event_adapter.validate_python(record.payload)
    for user_id in sorted(event_recipients(db, record)):
        preference = db.scalar(select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.event_type == data.event_type,
        ))
        if user_id == record.actor_id:
            continue
        in_app = preference.in_app_enabled if preference is not None else default_in_app(data.event_type)
        if in_app:
            existing = db.scalar(select(Notification.id).where(
                Notification.event_id == record.id, Notification.user_id == user_id,
            ))
            if existing is None:
                db.add(Notification(event_id=record.id, user_id=user_id))
        if in_app and preference is not None and preference.push_enabled and preference.data_mod <= record.created_at:
            from web_push import queue_push

            queue_push(db, record, user_id)
