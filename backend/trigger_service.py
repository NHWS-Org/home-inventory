import hashlib
import json
import logging
from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from zoneinfo import ZoneInfo

from filter_contracts import TriggerInput
from filter_service import (
    audit_fields, can_view_filter, compatible_inventories, evaluate_filter, filter_input, get_filter,
    is_admin, scope_preview, validate_filter, visible_inventories,
)
from models import (
    FilterTemplate, Inventory, MetadataDefinition, NotificationEvent, ScheduledTrigger, TriggerRun,
    TriggerSubscription, User,
)
from notification_contracts import FilterTriggerMatchedData
from notification_outbox import enqueue_event, utcnow

logger = logging.getLogger(__name__)
MAX_TRIGGERS_PER_TICK = 100
MAX_CONTAINERS = 100
MAX_SCANNED_PER_TICK = 1000
_scan_cursor = 0
CATCHUP = timedelta(hours=1)


def filter_fingerprint(db: Session, template: FilterTemplate) -> str:
    raw = [template.id, template.name, template.description, template.is_shared,
           template.inventory_id, template.criteria, str(template.data_ins)]
    payload = filter_input(db, template)
    for definition_id in sorted({condition.definition_id for condition in payload.conditions if condition.source == "metadata"}):
        definition = db.get(MetadataDefinition, definition_id)
        raw.append([
            definition.id, definition.key, definition.field_type, definition.is_active, definition.list_options,
            sorted({(assignment.scope, assignment.inventory_type or "", assignment.inventory_id or 0)
                    for assignment in definition.assignments}),
        ])
    return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()


def can_manage_trigger(user: User, trigger: ScheduledTrigger) -> bool:
    return not user.is_blocked and (is_admin(user) or trigger.user_ins == user.id)


def trigger_inventories(db: Session, user: User, trigger: ScheduledTrigger, template: FilterTemplate) -> list[Inventory]:
    if not can_view_filter(db, user, template):
        return []
    payload = filter_input(db, template)
    definitions = validate_filter(db, user, payload, zone=trigger.timezone)
    inventories = compatible_inventories(payload, visible_inventories(db, user, action="edit"), definitions)
    ids = trigger.inventory_ids
    if template.inventory_id is not None:
        ids = [template.inventory_id] if ids is None else [value for value in ids if value == template.inventory_id]
    return [inventory for inventory in inventories if ids is None or inventory.id in ids]


def can_subscribe(db: Session, user: User, trigger: ScheduledTrigger) -> bool:
    template = db.get(FilterTemplate, trigger.filter_id)
    if template is None or not can_view_filter(db, user, template):
        return False
    # A private filter may never be used by another user's trigger or subscription.
    if not template.is_shared and not (is_admin(user) or template.user_ins == user.id):
        return False
    try:
        return bool(trigger_inventories(db, user, trigger, template))
    except (HTTPException, ValueError, KeyError, TypeError):
        return False


def get_trigger(db: Session, user: User, trigger_id: int, *, manage: bool = False) -> ScheduledTrigger:
    trigger = db.get(ScheduledTrigger, trigger_id)
    if trigger is None:
        raise HTTPException(404, "Trigger non trovato")
    template = db.get(FilterTemplate, trigger.filter_id)
    if template is None or not can_view_filter(db, user, template):
        raise HTTPException(403, "Accesso negato")
    allowed = can_manage_trigger(user, trigger) if manage else can_manage_trigger(user, trigger) or can_subscribe(db, user, trigger)
    if not allowed:
        raise HTTPException(403, "Accesso negato")
    return trigger


def validate_trigger(db: Session, user: User, payload: TriggerInput) -> FilterTemplate:
    template = get_filter(db, user, payload.filter_id)
    if not template.is_shared and not (is_admin(user) or template.user_ins == user.id):
        raise HTTPException(403, "Un filtro privato richiede il proprietario")
    criteria = filter_input(db, template)
    definitions = validate_filter(db, user, criteria, zone=payload.timezone)
    inventories = compatible_inventories(criteria, visible_inventories(db, user, action="edit"), definitions)
    if template.inventory_id is not None:
        inventories = [inventory for inventory in inventories if inventory.id == template.inventory_id]
    eligible = {inventory.id for inventory in inventories}
    if payload.inventory_ids is not None and not set(payload.inventory_ids) <= eligible:
        raise HTTPException(403, "Contenitore non compatibile o non modificabile")
    if not eligible:
        raise HTTPException(403, "Nessun contenitore compatibile modificabile")
    if len(payload.inventory_ids if payload.inventory_ids is not None else eligible) > MAX_CONTAINERS:
        raise HTTPException(422, "Massimo 100 contenitori per trigger; selezionare un sottoinsieme")
    return template


def slot_on_day(trigger: ScheduledTrigger, day) -> datetime | None:
    if day.isoweekday() not in trigger.weekdays:
        return None
    zone = ZoneInfo(trigger.timezone)
    local = datetime.combine(day, time.fromisoformat(trigger.time), zone).replace(fold=0)
    instant = local.astimezone(timezone.utc)
    # A nonexistent wall-clock time does not round-trip. Repeated times use fold=0 once.
    if instant.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
        return None
    return instant.replace(tzinfo=None)


def next_slot(trigger: ScheduledTrigger, now: datetime | None = None, *, last_logical_date=None) -> datetime | None:
    if not trigger.enabled:
        return None
    current = now or utcnow()
    day = current.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(trigger.timezone)).date()
    for offset in range(9):
        slot = slot_on_day(trigger, day + timedelta(days=offset))
        # There is at most one execution per logical date, even after rescheduling.
        if slot is not None and slot > current:
            if trigger.last_run_at is not None or last_logical_date is not None:
                previous_day = last_logical_date or trigger.last_run_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(trigger.timezone)).date()
                if day + timedelta(days=offset) == previous_day:
                    continue
            return slot
    return None


def due_slot(trigger: ScheduledTrigger, now: datetime) -> datetime | None:
    day = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(trigger.timezone)).date()
    slots = [slot_on_day(trigger, day - timedelta(days=offset)) for offset in (0, 1)]
    slots = [slot for slot in slots if slot is not None and now - CATCHUP <= slot <= now and slot >= trigger.data_ins]
    return max(slots) if slots else None


def trigger_response(db: Session, user: User, trigger: ScheduledTrigger) -> dict:
    template = db.get(FilterTemplate, trigger.filter_id)
    try:
        payload = filter_input(db, template)
        definitions = validate_filter(db, user, payload, zone=trigger.timezone)
        scope = scope_preview(payload, trigger_inventories(db, user, trigger, template), definitions)
    except (HTTPException, ValueError, KeyError, TypeError):
        scope = {"scope_type": "none", "summary": "Filtro non più compatibile", "inventories": []}
    def as_utc(value):
        return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value
    last_logical_date = db.scalar(select(TriggerRun.logical_date).where(
        TriggerRun.trigger_id == trigger.id,
    ).order_by(TriggerRun.scheduled_at.desc()).limit(1))
    return {
        **{key: getattr(trigger, key) for key in TriggerInput.model_fields},
        "id": trigger.id, **audit_fields(trigger), "filter_name": template.name, "scope_preview": scope,
        "can_manage": can_manage_trigger(user, trigger), "last_run_at": as_utc(trigger.last_run_at),
        "next_run_at": as_utc(next_slot(trigger, last_logical_date=last_logical_date)), "last_result_count": trigger.last_result_count,
        "last_container_count": trigger.last_container_count, "last_error": trigger.last_error,
    }


def preview_trigger(db: Session, user: User, trigger: ScheduledTrigger) -> dict:
    template = get_filter(db, user, trigger.filter_id)
    inventories = trigger_inventories(db, user, trigger, template)
    return evaluate_filter(
        db, user, filter_input(db, template), inventory_ids=[inv.id for inv in inventories],
        zone=trigger.timezone, action="edit",
        legacy=not isinstance(template.criteria, dict) or template.criteria.get("version") != 2,
    )


def remove_trigger_events(db: Session, trigger_id: int) -> None:
    # Foreign-key cascades remove inbox and push deliveries; explicit ORM cleanup also
    # supports SQLite sessions with FK enforcement disabled by legacy test fixtures.
    from models import Notification, PushDelivery
    conditions = (
        NotificationEvent.payload["trigger_id"].as_integer() == trigger_id,
        NotificationEvent.payload["event_type"].as_string() == "filter_trigger_matched",
    )
    events = select(NotificationEvent.id).where(*conditions)
    db.execute(delete(PushDelivery).where(PushDelivery.event_id.in_(events)))
    db.execute(delete(Notification).where(Notification.event_id.in_(events)))
    db.execute(delete(NotificationEvent).where(*conditions))


def invalidate_filter_triggers(db: Session, filter_id: int) -> None:
    for trigger in db.scalars(select(ScheduledTrigger).where(ScheduledTrigger.filter_id == filter_id)):
        trigger.revision += 1
        trigger.baseline = None
        trigger.last_error = None
        remove_trigger_events(db, trigger.id)
        owner = db.get(User, trigger.user_ins)
        if owner is None or not can_subscribe(db, owner, trigger):
            trigger.enabled = False
            trigger.last_error = "filter_revoked"
        for subscription in db.scalars(select(TriggerSubscription).where(TriggerSubscription.trigger_id == trigger.id)):
            subscriber = db.get(User, subscription.user_id)
            if subscriber is None or not can_subscribe(db, subscriber, trigger):
                subscription.enabled = False


def delete_trigger(db: Session, trigger: ScheduledTrigger) -> None:
    remove_trigger_events(db, trigger.id)
    db.execute(delete(TriggerSubscription).where(TriggerSubscription.trigger_id == trigger.id))
    db.execute(delete(TriggerRun).where(TriggerRun.trigger_id == trigger.id))
    db.delete(trigger)


def delete_filter_triggers(db: Session, filter_id: int) -> None:
    for trigger in db.scalars(select(ScheduledTrigger).where(ScheduledTrigger.filter_id == filter_id)):
        delete_trigger(db, trigger)


def trigger_event_authorized(db: Session, user: User, record: NotificationEvent) -> bool:
    data = record.payload
    trigger = db.get(ScheduledTrigger, data["trigger_id"])
    template = db.get(FilterTemplate, data["filter_id"])
    if (
        trigger is None or template is None or not trigger.enabled
        or trigger.filter_id != template.id or trigger.revision != data["trigger_revision"]
        or not can_subscribe(db, user, trigger)
    ):
        return False
    if filter_fingerprint(db, template) != data["filter_fingerprint"]:
        return False
    owner = db.get(User, trigger.user_ins)
    if owner is None or not can_subscribe(db, owner, trigger):
        return False
    if not any(inv.id == data["inventory_id"] for inv in trigger_inventories(db, owner, trigger, template)):
        return False
    if not any(inv.id == data["inventory_id"] for inv in trigger_inventories(db, user, trigger, template)):
        return False
    subscription = db.scalar(select(TriggerSubscription).where(
        TriggerSubscription.trigger_id == trigger.id, TriggerSubscription.user_id == user.id,
        TriggerSubscription.enabled.is_(True),
    ))
    return subscription is not None and subscription.data_mod <= record.created_at


def run_trigger(factory: sessionmaker, trigger_id: int, now: datetime) -> bool:
    try:
        with factory.begin() as db:
            # Fence SQLite before reading, and lock the row on server databases.
            locked = db.execute(update(ScheduledTrigger).where(
                ScheduledTrigger.id == trigger_id, ScheduledTrigger.enabled.is_(True),
            ).values(revision=ScheduledTrigger.revision))
            if locked.rowcount != 1:
                return False
            trigger = db.scalar(select(ScheduledTrigger).where(
                ScheduledTrigger.id == trigger_id,
            ).with_for_update())
            slot = due_slot(trigger, now)
            if slot is None:
                return False
            logical_day = slot.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(trigger.timezone)).date()
            if db.scalar(select(TriggerRun.id).where(
                TriggerRun.trigger_id == trigger.id, TriggerRun.logical_date == logical_day,
            )) is not None:
                return False
            run = TriggerRun(trigger_id=trigger.id, scheduled_at=slot, logical_date=logical_day, status="completed")
            db.add(run)
            db.flush()
            try:
                with db.begin_nested():
                    owner = db.get(User, trigger.user_ins)
                    template = db.get(FilterTemplate, trigger.filter_id)
                    if owner is None or template is None or not can_view_filter(db, owner, template):
                        raise HTTPException(403, "Trigger non autorizzato")
                    payload = filter_input(db, template)
                    validate_filter(db, owner, payload, zone=trigger.timezone, now=slot)
                    if not can_subscribe(db, owner, trigger):
                        raise HTTPException(403, "Trigger non autorizzato")
                    inventories = trigger_inventories(db, owner, trigger, template)
                    if len(inventories) > MAX_CONTAINERS:
                        raise HTTPException(422, "Limite contenitori superato")
                    result = evaluate_filter(
                        db, owner, payload,
                        inventory_ids=[inv.id for inv in inventories],
                        zone=trigger.timezone, now=slot, action="edit",
                        legacy=not isinstance(template.criteria, dict) or template.criteria.get("version") != 2,
                    )
                    baseline = {str(container["id"]): container["item_ids"] for container in result["containers"]}
                    changed = trigger.baseline is None or baseline != trigger.baseline
                    trigger.baseline = baseline
                    run.result_count = trigger.last_result_count = result["total_count"]
                    run.container_count = trigger.last_container_count = len(result["containers"])
                    trigger.last_error = None
                    if result["total_count"] and (trigger.notify_mode == "always" or changed):
                        for container in result["containers"]:
                            enqueue_event(db, FilterTriggerMatchedData(
                                filter_id=template.id, trigger_id=trigger.id, inventory_id=container["id"],
                                filter_name=template.name, count=container["count"], scheduled_at=slot.isoformat() + "Z",
                                trigger_revision=trigger.revision, filter_fingerprint=filter_fingerprint(db, template),
                            ), actor_id=None, now=now)
            except OperationalError:
                raise
            except Exception as exc:
                run.status = "failed"
                code = (
                    "not_authorized" if isinstance(exc, HTTPException) and exc.status_code == 403
                    else "invalid_filter" if isinstance(exc, (HTTPException, ValueError, KeyError, TypeError))
                    else "evaluation_failed"
                )
                run.error = trigger.last_error = code
                logger.warning("Trigger %s failed: %s", trigger_id, code)
            trigger.last_run_at = slot
        return True
    except (IntegrityError, OperationalError):
        # Another worker may own the unique slot or the database is temporarily busy.
        # No partial run/event is committed; the next bounded tick retries.
        return False


def run_due_triggers(factory: sessionmaker, *, now: datetime | None = None) -> int:
    global _scan_cursor
    current = now or utcnow()
    with factory() as db:
        ids = []
        # Scan pages, but perform at most 100 evaluations per worker tick.
        cursor = _scan_cursor
        scanned = 0
        wrapped = False
        while len(ids) < MAX_TRIGGERS_PER_TICK and scanned < MAX_SCANNED_PER_TICK:
            triggers = db.scalars(select(ScheduledTrigger).where(
                ScheduledTrigger.enabled.is_(True), ScheduledTrigger.id > cursor,
            ).order_by(ScheduledTrigger.id).limit(100)).all()
            if not triggers:
                if cursor and not wrapped and scanned == 0:
                    cursor = 0
                    wrapped = True
                    continue
                cursor = 0
                break
            cursor = triggers[-1].id
            scanned += len(triggers)
            for trigger in triggers:
                try:
                    slot = due_slot(trigger, current)
                except (ValueError, KeyError):
                    continue
                if slot is None:
                    continue
                logical_day = slot.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(trigger.timezone)).date()
                if db.scalar(select(TriggerRun.id).where(
                    TriggerRun.trigger_id == trigger.id, TriggerRun.logical_date == logical_day,
                )) is None:
                    ids.append(trigger.id)
                    if len(ids) == MAX_TRIGGERS_PER_TICK:
                        cursor = trigger.id
                        break
        _scan_cursor = cursor
    return sum(run_trigger(factory, trigger_id, current) for trigger_id in ids)
