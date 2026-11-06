from typing import Literal
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    Inventory, Item, Notification, NotificationEvent, NotificationPreference,
    NotificationRule, User, UserGroupAssociation,
)
from notification_contracts import (
    ChecklistCompletedData, InventorySharedData, ItemQuantityChangedData,
    NotificationRuleInput, notification_event_adapter,
)
from notification_outbox import enqueue_event, utcnow
from quantity_changes import QUANTITY_MERGE_WINDOW_SECONDS


def can_receive(user: User, inventory: Inventory) -> bool:
    from routes.inventory import can_access_inventory

    return bool(
        not user.is_blocked and user.role is not None
        and can_access_inventory(user, inventory, action="view")
    )


def configured(db: Session, inventory_id: int, event_type: str) -> bool:
    return db.scalar(select(NotificationRule.id).where(
        NotificationRule.inventory_id == inventory_id,
        NotificationRule.event_type == event_type,
        NotificationRule.enabled.is_(True),
    ).limit(1)) is not None


def emit_share(
    db: Session, inventory_id: int, kind: Literal["user", "group"],
    recipient_id: int, actor_id: int,
) -> None:
    if configured(db, inventory_id, "inventory_shared"):
        enqueue_event(db, InventorySharedData(
            inventory_id=inventory_id, recipient_kind=kind, recipient_id=recipient_id,
        ), actor_id=actor_id)


def emit_item_change(
    db: Session, item: Item, previous: dict, actor_id: int, *,
    now: datetime | None = None, merge_previous_at: datetime | None = None,
) -> None:
    old = previous.get("quantity") or 0
    new = item.quantity or 0
    if old == new or previous["inventory_id"] != item.inventory_id:
        return
    inventory = db.get(Inventory, item.inventory_id)
    if inventory is None:
        return
    current = now or utcnow()
    available_at = current + timedelta(seconds=QUANTITY_MERGE_WINDOW_SECONDS)
    if inventory.type == "INVENTORY" and configured(db, inventory.id, "item_quantity_changed"):
        pending = None
        if merge_previous_at is not None:
            pending = db.scalar(select(NotificationEvent).where(
                NotificationEvent.status == "pending",
                NotificationEvent.attempts == 0,
                NotificationEvent.actor_id == actor_id,
                NotificationEvent.payload["event_type"].as_string() == "item_quantity_changed",
                NotificationEvent.payload["item_id"].as_integer() == item.id,
                NotificationEvent.payload["inventory_id"].as_integer() == inventory.id,
                NotificationEvent.available_at == merge_previous_at + timedelta(
                    seconds=QUANTITY_MERGE_WINDOW_SECONDS,
                ),
                NotificationEvent.available_at >= current,
            ).with_for_update())
        initial = pending.payload["previous_quantity"] if pending is not None else old
        if initial == new:
            if pending is not None:
                db.delete(pending)
            return
        data = ItemQuantityChangedData(
            inventory_id=inventory.id, item_id=item.id, previous_quantity=initial, quantity=new,
        )
        if pending is None:
            pending = enqueue_event(db, data, actor_id=actor_id, now=current)
        else:
            pending.payload = data.model_dump(mode="json")
        pending.available_at = available_at
    if inventory.type == "CHECKLIST":
        pending_completions = db.scalars(select(NotificationEvent).where(
            NotificationEvent.status == "pending",
            NotificationEvent.attempts == 0,
            NotificationEvent.payload["event_type"].as_string() == "checklist_completed",
            NotificationEvent.payload["inventory_id"].as_integer() == inventory.id,
            NotificationEvent.available_at >= current,
        ).with_for_update()).all()
        with db.no_autoflush:
            others = db.scalars(select(Item).where(
                Item.inventory_id == inventory.id, Item.id != item.id,
            )).all()
        complete = new >= 1 and all((other.quantity or 0) >= 1 for other in others)
        for pending in pending_completions:
            if complete:
                pending.available_at = available_at
            else:
                db.delete(pending)
        if (
            complete and old < 1 <= new and not pending_completions
            and configured(db, inventory.id, "checklist_completed")
        ):
            pending = enqueue_event(
                db, ChecklistCompletedData(inventory_id=inventory.id),
                actor_id=actor_id, now=current,
            )
            pending.available_at = available_at


def group_users(db: Session, group_id: int) -> set[int]:
    return set(db.scalars(select(UserGroupAssociation.user_id).where(
        UserGroupAssociation.group_id == group_id,
    )))


def evaluate_event(db: Session, record: NotificationEvent) -> None:
    data = notification_event_adapter.validate_python(record.payload)
    inventory = db.get(Inventory, data.inventory_id)
    if inventory is None:
        return
    if isinstance(data, ItemQuantityChangedData):
        item = db.get(Item, data.item_id)
        if item is None or item.inventory_id != inventory.id:
            return
    rules = db.scalars(select(NotificationRule).where(
        NotificationRule.inventory_id == inventory.id,
        NotificationRule.event_type == data.event_type,
        NotificationRule.enabled.is_(True),
        NotificationRule.data_ins <= record.created_at,
        NotificationRule.data_mod <= record.created_at,
    )).all()
    recipients: set[int] = set()
    for rule in rules:
        config = NotificationRuleInput(
            event_type=rule.event_type, threshold=rule.threshold, recipients=rule.recipients,
            enabled=rule.enabled,
        )
        if isinstance(data, ItemQuantityChangedData) and not (
            data.previous_quantity >= config.threshold > data.quantity
        ):
            continue
        for recipient in config.recipients:
            if recipient.kind == "owner" and inventory.owner_id is not None:
                recipients.add(inventory.owner_id)
            elif recipient.kind == "participants":
                if inventory.owner_id is not None:
                    recipients.add(inventory.owner_id)
                recipients.update(share.user_id for share in inventory.shared_with_users)
                for share in inventory.shared_with_groups:
                    recipients.update(group_users(db, share.group_id))
            elif recipient.kind == "user":
                recipients.add(recipient.id)
            elif recipient.kind == "group":
                recipients.update(group_users(db, recipient.id))
            elif recipient.kind == "event_recipient" and isinstance(data, InventorySharedData):
                if data.recipient_kind == "user":
                    recipients.add(data.recipient_id)
                else:
                    recipients.update(group_users(db, data.recipient_id))
    for user_id in sorted(recipients):
        user = db.get(User, user_id)
        if user is None or not can_receive(user, inventory):
            continue
        preference = db.scalar(select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.event_type == data.event_type,
        ))
        if preference is not None and not preference.in_app_enabled:
            continue
        if user_id == record.actor_id and (
            preference is None or not preference.include_own_actions
        ):
            continue
        existing = db.scalar(select(Notification.id).where(
            Notification.event_id == record.id, Notification.user_id == user_id,
        ))
        if existing is None:
            db.add(Notification(event_id=record.id, user_id=user_id))
