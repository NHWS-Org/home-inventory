from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from dependencies import get_current_user, get_db
from models import (
    Group, Inventory, Notification, NotificationEvent, NotificationPreference, NotificationRule,
    User, UserGroupAssociation,
)
from notification_contracts import (
    NotificationEventType, NotificationPreferenceInput, NotificationRuleInput,
    notification_event_adapter,
)
from notification_outbox import utcnow
from notification_rules import can_receive
from routes.push import router as push_router

router = APIRouter()


def managed_inventory(db: Session, user: User, inventory_id: int) -> Inventory:
    inventory = db.get(Inventory, inventory_id)
    if inventory is None:
        raise HTTPException(404, "Inventario non trovato")
    if user.role.name != "admin" and inventory.owner_id != user.id:
        raise HTTPException(403, "Solo proprietario o admin possono gestire le regole")
    return inventory


def validate_scope(db: Session, inventory: Inventory, config: NotificationRuleInput) -> None:
    if (
        config.event_type == "item_quantity_changed" and inventory.type != "INVENTORY"
        or config.event_type == "checklist_completed" and inventory.type != "CHECKLIST"
    ):
        raise HTTPException(422, "Evento non disponibile per questo tipo di contenitore")
    for recipient in config.recipients:
        if recipient.kind == "user":
            user = db.get(User, recipient.id)
            if user is None or not can_receive(user, inventory):
                raise HTTPException(422, "Destinatario non autorizzato")
        elif recipient.kind == "group":
            group = db.get(Group, recipient.id)
            if group is None or not any(
                share.group_id == recipient.id for share in inventory.shared_with_groups
            ):
                raise HTTPException(422, "Gruppo non condiviso con il contenitore")


def rule_response(rule: NotificationRule) -> dict:
    return {
        "id": rule.id, "inventory_id": rule.inventory_id, "event_type": rule.event_type,
        "threshold": rule.threshold, "recipients": rule.recipients, "enabled": rule.enabled,
    }


@router.get("/rules/{inventory_id}")
def list_rules(inventory_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    managed_inventory(db, user, inventory_id)
    return [rule_response(rule) for rule in db.scalars(select(NotificationRule).where(
        NotificationRule.inventory_id == inventory_id,
    ).order_by(NotificationRule.id))]


@router.get("/rules/{inventory_id}/recipients")
def rule_recipients(
    inventory_id: int, db: Session = Depends(get_db), user=Depends(get_current_user),
):
    inventory = managed_inventory(db, user, inventory_id)
    group_ids = {share.group_id for share in inventory.shared_with_groups}
    user_ids = {share.user_id for share in inventory.shared_with_users}
    if inventory.owner_id is not None:
        user_ids.add(inventory.owner_id)
    if group_ids:
        user_ids.update(db.scalars(select(UserGroupAssociation.user_id).where(
            UserGroupAssociation.group_id.in_(group_ids),
        )))
    users = db.scalars(select(User).where(User.id.in_(user_ids)).order_by(
        User.username, User.id,
    )).all() if user_ids else []
    groups = {
        share.group_id: share.group.name for share in inventory.shared_with_groups
    }
    return {
        "users": [
            {"id": recipient.id, "username": recipient.username}
            for recipient in users if can_receive(recipient, inventory)
        ],
        "groups": [
            {"id": group_id, "name": name}
            for group_id, name in sorted(groups.items(), key=lambda entry: (entry[1], entry[0]))
        ],
    }


@router.post("/rules/{inventory_id}", status_code=201)
def create_rule(
    inventory_id: int, payload: NotificationRuleInput,
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    inventory = managed_inventory(db, user, inventory_id)
    validate_scope(db, inventory, payload)
    rule = NotificationRule(
        inventory_id=inventory_id, **payload.model_dump(),
        data_ins=utcnow(), data_mod=utcnow(), user_ins=user.id, user_mod=user.id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule_response(rule)


@router.put("/rules/{inventory_id}/{rule_id}")
def update_rule(
    inventory_id: int, rule_id: int, payload: NotificationRuleInput,
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    inventory = managed_inventory(db, user, inventory_id)
    rule = db.get(NotificationRule, rule_id)
    if rule is None or rule.inventory_id != inventory_id:
        raise HTTPException(404, "Regola non trovata")
    validate_scope(db, inventory, payload)
    for name, value in payload.model_dump().items():
        setattr(rule, name, value)
    rule.user_mod = user.id
    rule.data_mod = utcnow()
    db.commit()
    return rule_response(rule)


@router.delete("/rules/{inventory_id}/{rule_id}")
def delete_rule(
    inventory_id: int, rule_id: int, db: Session = Depends(get_db), user=Depends(get_current_user),
):
    managed_inventory(db, user, inventory_id)
    rule = db.get(NotificationRule, rule_id)
    if rule is None or rule.inventory_id != inventory_id:
        raise HTTPException(404, "Regola non trovata")
    db.delete(rule)
    db.commit()
    return {"message": "Regola eliminata"}


@router.get("/preferences")
def preferences(db: Session = Depends(get_db), user=Depends(get_current_user)):
    stored = {row.event_type: row for row in db.scalars(select(NotificationPreference).where(
        NotificationPreference.user_id == user.id,
    ))}
    return [{
        "event_type": kind.value,
        "in_app_enabled": stored[kind.value].in_app_enabled if kind.value in stored else True,
        "push_enabled": stored[kind.value].push_enabled if kind.value in stored else False,
        "include_own_actions": stored[kind.value].include_own_actions if kind.value in stored else False,
    } for kind in NotificationEventType]


@router.put("/preferences/{event_type}")
def set_preference(
    event_type: NotificationEventType, payload: NotificationPreferenceInput,
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    row = db.scalar(select(NotificationPreference).where(
        NotificationPreference.user_id == user.id,
        NotificationPreference.event_type == event_type.value,
    ))
    if row is None:
        row = NotificationPreference(
            user_id=user.id, event_type=event_type.value, user_ins=user.id,
        )
        db.add(row)
    row.in_app_enabled = payload.in_app_enabled
    row.push_enabled = payload.push_enabled
    row.include_own_actions = payload.include_own_actions
    row.user_mod = user.id
    db.commit()
    return {"event_type": event_type.value, **payload.model_dump()}


def accessible_notification_context(
    db: Session, row: Notification, user: User,
) -> tuple[NotificationEvent, Inventory] | None:
    record = db.get(NotificationEvent, row.event_id)
    if record is None or record.schema_version != 1:
        return None
    data = notification_event_adapter.validate_python(record.payload)
    inventory = db.get(Inventory, data.inventory_id)
    return (record, inventory) if inventory is not None and can_receive(user, inventory) else None


def accessible_notification(db: Session, row: Notification, user: User) -> NotificationEvent | None:
    context = accessible_notification_context(db, row, user)
    return context[0] if context is not None else None


def accessible_notifications(db: Session, user: User, *, unread_only: bool = False):
    last_id = None
    while True:
        query = select(Notification).where(Notification.user_id == user.id)
        if unread_only:
            query = query.where(Notification.read_at.is_(None))
        if last_id is not None:
            query = query.where(Notification.id < last_id)
        rows = db.scalars(query.order_by(Notification.id.desc()).limit(100)).all()
        if not rows:
            break
        last_id = rows[-1].id
        for row in rows:
            context = accessible_notification_context(db, row, user)
            if context is not None:
                yield row, context[0], context[1]


@router.get("")
def inbox(
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    result = []
    skipped = 0
    for row, record, inventory in accessible_notifications(db, user):
        if skipped < offset:
            skipped += 1
            continue
        result.append({
            "id": row.id, "created_at": row.created_at, "read_at": row.read_at,
            "event": record.payload, "inventory_type": inventory.type,
            "inventory_name": inventory.name,
        })
        if len(result) == limit:
            break
    return result


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return {"count": sum(1 for _ in accessible_notifications(db, user, unread_only=True))}


@router.put("/read-all")
def read_all(db: Session = Depends(get_db), user=Depends(get_current_user)):
    read_at = utcnow()
    updated = 0
    for row, _record, _inventory in accessible_notifications(db, user, unread_only=True):
        row.read_at = read_at
        updated += 1
    if updated:
        db.commit()
    return {"updated": updated}


@router.put("/{notification_id}/read")
def read_notification(
    notification_id: int, db: Session = Depends(get_db), user=Depends(get_current_user),
):
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id or accessible_notification(db, row, user) is None:
        raise HTTPException(404, "Notifica non trovata")
    if row.read_at is None:
        row.read_at = utcnow()
        db.commit()
    return {"id": row.id, "read_at": row.read_at}


router.include_router(push_router, prefix="/push")
