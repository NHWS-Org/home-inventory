from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from dependencies import get_current_user, get_db
from filter_contracts import (
    EvaluationInput, EvaluationResponse, FilterField, FilterInput, FilterPreviewInput, FilterResponse,
)
from filter_service import (
    can_view_filter, evaluate_filter, field_catalog, filter_input, filter_response,
    get_filter, persist_filter, validate_filter,
)
from models import FilterTemplate, User

router = APIRouter()


@router.get("/fields", response_model=list[FilterField], response_model_exclude_none=True)
def fields(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return field_catalog(db, user)


@router.post("/preview", response_model=EvaluationResponse)
def preview(payload: FilterPreviewInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    criteria = FilterInput.model_validate(payload.model_dump(exclude={"inventory_id", "timezone"}))
    return evaluate_filter(
        db, user, criteria, inventory_ids=[payload.inventory_id] if payload.inventory_id is not None else None,
        zone=payload.timezone,
    )


@router.get("", response_model=list[FilterResponse])
def list_filters(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [
        filter_response(db, user, template)
        for template in db.scalars(select(FilterTemplate).order_by(FilterTemplate.id))
        if can_view_filter(db, user, template)
    ]


@router.post("", status_code=201, response_model=FilterResponse)
def create_filter(payload: FilterInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    validate_filter(db, user, payload)
    if db.scalar(select(FilterTemplate.id).where(
        FilterTemplate.user_ins == user.id, FilterTemplate.name == payload.name,
    )) is not None:
        raise HTTPException(409, "Esiste già un filtro con questo nome")
    template = FilterTemplate(user_ins=user.id, inventory_id=None)
    persist_filter(template, payload, user)
    db.add(template)
    db.commit()
    db.refresh(template)
    return filter_response(db, user, template)


@router.get("/{filter_id}", response_model=FilterResponse)
def read_filter(filter_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return filter_response(db, user, get_filter(db, user, filter_id))


@router.patch("/{filter_id}", response_model=FilterResponse)
def update_filter(
    filter_id: int, updates: dict = Body(...),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    template = get_filter(db, user, filter_id, manage=True)
    try:
        current = filter_input(db, template).model_dump(mode="json")
    except (HTTPException, ValueError, KeyError, TypeError):
        current = {"name": template.name, "description": template.description, "is_shared": template.is_shared}
    from pydantic import ValidationError
    try:
        payload = FilterInput.model_validate({**current, **updates})
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False)) from None
    validate_filter(db, user, payload)
    if db.scalar(select(FilterTemplate.id).where(
        FilterTemplate.user_ins == template.user_ins, FilterTemplate.name == payload.name,
        FilterTemplate.id != template.id,
    )) is not None:
        raise HTTPException(409, "Esiste già un filtro con questo nome")
    persist_filter(template, payload, user)
    from trigger_service import invalidate_filter_triggers
    invalidate_filter_triggers(db, template.id)
    db.commit()
    db.refresh(template)
    return filter_response(db, user, template)


@router.delete("/{filter_id}")
def delete_filter(filter_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    template = get_filter(db, user, filter_id, manage=True)
    from trigger_service import delete_filter_triggers
    delete_filter_triggers(db, template.id)
    db.delete(template)
    db.commit()
    return {"detail": "Filtro eliminato"}


@router.post("/{filter_id}/evaluate", response_model=EvaluationResponse)
def evaluate(
    filter_id: int, payload: EvaluationInput = Body(default_factory=EvaluationInput),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    template = get_filter(db, user, filter_id)
    ids = [payload.inventory_id] if payload.inventory_id is not None else None
    if template.inventory_id is not None:
        if ids is not None and ids != [template.inventory_id]:
            raise HTTPException(422, "Filtro legacy limitato al contenitore originale")
        ids = [template.inventory_id]
    return evaluate_filter(
        db, user, filter_input(db, template), inventory_ids=ids, zone=payload.timezone,
        legacy=not isinstance(template.criteria, dict) or template.criteria.get("version") != 2,
    )
