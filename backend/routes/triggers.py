from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dependencies import get_current_user, get_db
from filter_contracts import EvaluationResponse, SubscriptionInput, TriggerInput, TriggerResponse
from filter_service import can_view_filter
from models import FilterTemplate, ScheduledTrigger, TriggerSubscription, User
from trigger_service import (
    can_manage_trigger, can_subscribe, delete_trigger, get_trigger,
    preview_trigger, remove_trigger_events, trigger_response, validate_trigger,
)

router = APIRouter()


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Nome o sottoscrizione già esistente") from None


@router.get("/subscriptions")
def subscriptions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = []
    for subscription in db.scalars(select(TriggerSubscription).where(TriggerSubscription.user_id == user.id)):
        trigger = db.get(ScheduledTrigger, subscription.trigger_id)
        if trigger is not None and can_subscribe(db, user, trigger):
            result.append({"trigger_id": trigger.id, "enabled": subscription.enabled})
    return result


@router.get("", response_model=list[TriggerResponse])
def list_triggers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = []
    for trigger in db.scalars(select(ScheduledTrigger).order_by(ScheduledTrigger.id)):
        template = db.get(FilterTemplate, trigger.filter_id)
        if template is not None and can_view_filter(db, user, template) and (
            can_manage_trigger(user, trigger) or can_subscribe(db, user, trigger)
        ):
            result.append(trigger_response(db, user, trigger))
    return result


@router.post("", status_code=201, response_model=TriggerResponse)
def create_trigger(payload: TriggerInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    validate_trigger(db, user, payload)
    if db.query(ScheduledTrigger).filter(ScheduledTrigger.user_ins == user.id).count() >= 100:
        raise HTTPException(422, "Massimo 100 trigger per utente")
    trigger = ScheduledTrigger(**payload.model_dump(), user_ins=user.id, user_mod=user.id)
    db.add(trigger)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Esiste già un trigger con questo nome") from None
    # The creator explicitly opts into their own schedule; the category still defaults off.
    db.add(TriggerSubscription(trigger_id=trigger.id, user_id=user.id, enabled=True, user_ins=user.id, user_mod=user.id))
    commit(db)
    db.refresh(trigger)
    return trigger_response(db, user, trigger)


@router.get("/{trigger_id}", response_model=TriggerResponse)
def read_trigger(trigger_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return trigger_response(db, user, get_trigger(db, user, trigger_id))


@router.patch("/{trigger_id}", response_model=TriggerResponse)
def update_trigger(
    trigger_id: int, updates: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    trigger = get_trigger(db, user, trigger_id, manage=True)
    current = {key: getattr(trigger, key) for key in TriggerInput.model_fields}
    try:
        payload = TriggerInput.model_validate({**current, **updates})
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False)) from None
    validate_trigger(db, user, payload)
    if current != payload.model_dump():
        for key, value in payload.model_dump().items():
            setattr(trigger, key, value)
        trigger.revision += 1
        trigger.baseline = None
        trigger.last_error = None
        trigger.user_mod = user.id
        remove_trigger_events(db, trigger.id)
    commit(db)
    db.refresh(trigger)
    return trigger_response(db, user, trigger)


@router.delete("/{trigger_id}")
def remove_trigger(trigger_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    delete_trigger(db, get_trigger(db, user, trigger_id, manage=True))
    commit(db)
    return {"detail": "Trigger eliminato"}


@router.post("/{trigger_id}/preview", response_model=EvaluationResponse)
def preview(trigger_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return preview_trigger(db, user, get_trigger(db, user, trigger_id))


@router.put("/{trigger_id}/subscription")
def set_subscription(
    trigger_id: int, payload: SubscriptionInput,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    trigger = get_trigger(db, user, trigger_id)
    if not can_subscribe(db, user, trigger):
        raise HTTPException(403, "Trigger non sottoscrivibile")
    row = db.scalar(select(TriggerSubscription).where(
        TriggerSubscription.trigger_id == trigger.id, TriggerSubscription.user_id == user.id,
    ))
    if row is None:
        row = TriggerSubscription(trigger_id=trigger.id, user_id=user.id, user_ins=user.id)
        db.add(row)
    row.enabled = payload.enabled
    row.user_mod = user.id
    commit(db)
    return {"trigger_id": trigger.id, "enabled": row.enabled}
