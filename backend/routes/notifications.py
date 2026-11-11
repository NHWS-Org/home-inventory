from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from dependencies import get_current_user, get_db
from models import Inventory, Item, Notification, NotificationEvent, NotificationPreference, User
from notification_contracts import NotificationBulkAction, NotificationEventType, NotificationPreferenceInput
from notification_outbox import utcnow
from notification_service import can_receive, default_in_app, event_inventory
from routes.push import router as push_router

router = APIRouter()


@router.get("/preferences")
def preferences(db: Session = Depends(get_db), user=Depends(get_current_user)):
    stored = {row.event_type: row for row in db.scalars(select(NotificationPreference).where(
        NotificationPreference.user_id == user.id,
    ))}
    return [{
        "event_type": kind.value,
        "in_app_enabled": stored[kind.value].in_app_enabled if kind.value in stored else default_in_app(kind.value),
        "push_enabled": stored[kind.value].push_enabled if kind.value in stored else False,
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
    settings = payload.model_dump()
    row.in_app_enabled = payload.in_app_enabled
    row.push_enabled = payload.push_enabled
    row.user_mod = user.id
    db.commit()
    return {"event_type": event_type.value, **settings}


def accessible_notification_context(
    db: Session, row: Notification, user: User,
) -> tuple[NotificationEvent, Inventory] | None:
    record = db.get(NotificationEvent, row.event_id)
    if record is None or record.schema_version != 1:
        return None
    inventory = event_inventory(db, record)
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


def action_time(record: NotificationEvent) -> datetime:
    value = record.payload.get("action_at")
    result = datetime.fromisoformat(value) if value else record.created_at
    return result.astimezone(timezone.utc).replace(tzinfo=None) if result.tzinfo else result


@router.get("")
def inbox(
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    result = []
    authorized = sorted(
        accessible_notifications(db, user),
        key=lambda entry: (action_time(entry[1]), entry[0].id), reverse=True,
    )
    for row, record, inventory in authorized[offset:offset + limit]:
        item_id = record.payload.get("item_id")
        item = db.get(Item, item_id) if item_id is not None else None
        result.append({
            "id": row.id, "created_at": row.created_at, "read_at": row.read_at,
            "action_at": action_time(record),
            "event": record.payload, "inventory_type": inventory.type,
            "inventory_name": inventory.name, "item_name": item.name if item is not None else None,
        })
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


def change_notifications(db: Session, user: User, payload: NotificationBulkAction) -> dict[str, int]:
    if payload.all:
        rows = [row for row, _record, _inventory in accessible_notifications(db, user)]
    else:
        rows = list(db.scalars(select(Notification).where(
            Notification.user_id == user.id, Notification.id.in_(set(payload.ids)),
        )))
        if len(rows) != len(set(payload.ids)) or any(
            accessible_notification(db, row, user) is None for row in rows
        ):
            raise HTTPException(404, "Notifica non trovata o accesso revocato")
    changed = 0
    read_at = utcnow()
    for row in rows:
        if payload.action == "delete":
            db.delete(row)
            changed += 1
        elif row.read_at is None:
            row.read_at = read_at
            changed += 1
    if changed:
        db.commit()
    return {"updated": changed}


@router.post("/bulk")
def bulk_notifications(
    payload: NotificationBulkAction, db: Session = Depends(get_db), user=Depends(get_current_user),
):
    return change_notifications(db, user, payload)


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: int = Path(gt=0), db: Session = Depends(get_db), user=Depends(get_current_user),
):
    return change_notifications(db, user, NotificationBulkAction(action="delete", ids=[notification_id]))


@router.put("/events/{event_key}/read")
def read_event_notification(
    event_key: UUID, db: Session = Depends(get_db), user=Depends(get_current_user),
):
    row = db.scalar(select(Notification).join(
        NotificationEvent, NotificationEvent.id == Notification.event_id,
    ).where(Notification.user_id == user.id, NotificationEvent.event_key == str(event_key)))
    if row is None:
        raise HTTPException(404, "Notifica non trovata")
    return read_notification(row.id, db, user)


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
