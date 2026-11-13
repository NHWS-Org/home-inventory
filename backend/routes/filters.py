from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from dependencies import get_db
from models import FilterTemplate, Inventory, MetadataDefinitionAssignment, RoleEnum, User
from routes.auth import get_current_user
from routes.inventory import can_access_inventory
from schemas import (
    FilterTemplateCreate,
    FilterTemplateListResponse,
    FilterTemplateResponse,
    FilterTemplateScopeInventory,
    FilterTemplateScopePreview,
    FilterTemplateUpdate,
)


router = APIRouter()


def _get_inventory_or_404(db: Session, inventory_id: int) -> Inventory:
    inventory = db.query(Inventory).filter(Inventory.id == inventory_id).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    return inventory


def _get_filter_template_or_404(db: Session, template_id: int) -> FilterTemplate:
    template = db.query(FilterTemplate).filter(FilterTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template filtro non trovato")
    return template


def _extract_definition_ids_from_criteria(criteria: object) -> list[int]:
    ids: list[int] = []
    if isinstance(criteria, dict):
        entries = criteria.get("criteria", [])
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and "definition_id" in entry:
                    try:
                        ids.append(int(entry["definition_id"]))
                    except (TypeError, ValueError):
                        pass
    elif isinstance(criteria, list):
        for entry in criteria:
            if isinstance(entry, dict) and "definition_id" in entry:
                try:
                    ids.append(int(entry["definition_id"]))
                except (TypeError, ValueError):
                    pass
    return list(set(ids))


def _count_criteria(criteria: object) -> int:
    if isinstance(criteria, dict):
        items = criteria.get("criteria", [])
        if isinstance(items, list):
            return len(items)
    elif isinstance(criteria, list):
        return len(criteria)
    return 0


def _is_compatible_with_inventory(
    assignments_by_def: dict[int, list[MetadataDefinitionAssignment]],
    inventory: Inventory,
    definition_ids: list[int],
) -> bool:
    if not definition_ids:
        return True

    inv_type = inventory.type
    for definition_id in definition_ids:
        assignments = assignments_by_def.get(definition_id, [])
        applicable = any(
            assignment.scope == "GLOBAL"
            or (assignment.scope == "INVENTORY_TYPE" and assignment.inventory_type == inv_type)
            or (assignment.scope == "INVENTORY" and assignment.inventory_id == inventory.id)
            for assignment in assignments
        )
        if not applicable:
            return False
    return True


def _compute_scope_preview_from_loaded_data(
    definition_ids: list[int],
    assignments_by_def: dict[int, list[MetadataDefinitionAssignment]],
    all_inventories: list[Inventory],
) -> FilterTemplateScopePreview:
    if not definition_ids:
        return FilterTemplateScopePreview(
            scope_type="none",
            summary="Nessun campo selezionato",
            inventories=[],
        )

    for definition_id in definition_ids:
        if definition_id not in assignments_by_def or not assignments_by_def[definition_id]:
            return FilterTemplateScopePreview(
                scope_type="none",
                summary="Uno o più campi non sono assegnati a nessun contenitore",
                inventories=[],
            )

    def covers_all_inventories(definition_id: int) -> bool:
        return any(
            assignment.scope == "GLOBAL"
            or (assignment.scope == "INVENTORY_TYPE" and assignment.inventory_type == "INVENTORY")
            for assignment in assignments_by_def.get(definition_id, [])
        )

    def covers_all_checklists(definition_id: int) -> bool:
        return any(
            assignment.scope == "GLOBAL"
            or (assignment.scope == "INVENTORY_TYPE" and assignment.inventory_type == "CHECKLIST")
            for assignment in assignments_by_def.get(definition_id, [])
        )

    all_cover_inventories = all(covers_all_inventories(definition_id) for definition_id in definition_ids)
    all_cover_checklists = all(covers_all_checklists(definition_id) for definition_id in definition_ids)

    if all_cover_inventories and all_cover_checklists:
        return FilterTemplateScopePreview(
            scope_type="global",
            summary="Visibile su tutti gli inventari e le checklist",
            inventories=[],
        )

    if all_cover_inventories:
        return FilterTemplateScopePreview(
            scope_type="all_inventories",
            summary="Visibile su tutti gli inventari",
            inventories=[],
        )

    if all_cover_checklists:
        return FilterTemplateScopePreview(
            scope_type="all_checklists",
            summary="Visibile su tutte le checklist",
            inventories=[],
        )

    compatible_inventories = [
        FilterTemplateScopeInventory(id=inv.id, name=inv.name, type=inv.type)
        for inv in all_inventories
        if _is_compatible_with_inventory(assignments_by_def, inv, definition_ids)
    ]

    if not compatible_inventories:
        return FilterTemplateScopePreview(
            scope_type="none",
            summary="Nessun contenitore compatibile",
            inventories=[],
        )

    return FilterTemplateScopePreview(
        scope_type="specific",
        summary=f"Visibile su {len(compatible_inventories)} contenitori compatibili",
        inventories=compatible_inventories,
    )


def _compute_scope_preview(
    db: Session, definition_ids: list[int], user: User
) -> FilterTemplateScopePreview:
    if not definition_ids:
        return FilterTemplateScopePreview(
            scope_type="none",
            summary="Nessun campo selezionato",
            inventories=[],
        )

    assignments = db.query(MetadataDefinitionAssignment).filter(
        MetadataDefinitionAssignment.definition_id.in_(definition_ids)
    ).all()
    assignments_by_def: dict[int, list[MetadataDefinitionAssignment]] = {}
    for assignment in assignments:
        assignments_by_def.setdefault(assignment.definition_id, []).append(assignment)

    # Restringe l'elenco agli inventari visibili dall'utente per evitare Information Disclosure
    all_inventories = [
        inv for inv in db.query(Inventory).all()
        if can_access_inventory(user, inv, action="view")
    ]
    return _compute_scope_preview_from_loaded_data(definition_ids, assignments_by_def, all_inventories)


class FilterTemplateListWithScope(FilterTemplateListResponse):
    scope_preview: Optional[FilterTemplateScopePreview] = None

    class Config:
        from_attributes = True


@router.get("/scope-preview", response_model=FilterTemplateScopePreview)
def get_scope_preview(
    definition_ids: str = Query(..., description="Lista di definition_id separati da virgola"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        ids = [int(item.strip()) for item in definition_ids.split(",") if item.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="definition_ids non valido")
    return _compute_scope_preview(db, ids, current_user)


@router.get("", response_model=List[FilterTemplateListWithScope])
def list_filter_templates(
    inventory_id: int = Query(..., gt=0),
    include_shared: bool = Query(True),
    include_incompatible: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inventory = _get_inventory_or_404(db, inventory_id)
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    query = db.query(FilterTemplate)
    if user.role.name != RoleEnum.admin.value:
        if include_shared:
            query = query.filter(
                or_(FilterTemplate.is_shared.is_(True), FilterTemplate.user_ins == user.id)
            )
        else:
            query = query.filter(
                FilterTemplate.is_shared.is_(False), FilterTemplate.user_ins == user.id
            )
    elif not include_shared:
        query = query.filter(FilterTemplate.is_shared.is_(False))
    templates = query.order_by(FilterTemplate.data_mod.desc(), FilterTemplate.id.asc()).all()

    if not templates:
        return []

    template_definition_ids: dict[int, list[int]] = {}
    all_definition_ids: set[int] = set()
    for template in templates:
        definition_ids = _extract_definition_ids_from_criteria(template.criteria)
        template_definition_ids[template.id] = definition_ids
        all_definition_ids.update(definition_ids)

    assignments_by_def: dict[int, list[MetadataDefinitionAssignment]] = {}
    if all_definition_ids:
        assignments = db.query(MetadataDefinitionAssignment).filter(
            MetadataDefinitionAssignment.definition_id.in_(all_definition_ids)
        ).all()
        for assignment in assignments:
            assignments_by_def.setdefault(assignment.definition_id, []).append(assignment)

    # Restringe l'elenco agli inventari visibili dall'utente per evitare Information Disclosure
    all_inventories = [
        inv for inv in db.query(Inventory).all()
        if can_access_inventory(user, inv, action="view")
    ]

    result: list[FilterTemplateListWithScope] = []
    for template in templates:
        if isinstance(template.criteria, dict) and template.criteria.get("version") == 2:
            continue
        definition_ids = template_definition_ids.get(template.id, [])
        if not include_incompatible and not _is_compatible_with_inventory(assignments_by_def, inventory, definition_ids):
            continue

        scope_preview = _compute_scope_preview_from_loaded_data(
            definition_ids,
            assignments_by_def,
            all_inventories,
        )

        result.append(
            FilterTemplateListWithScope(
                id=template.id,
                inventory_id=template.inventory_id,
                name=template.name,
                description=template.description,
                filter_type=template.filter_type,
                criteria_count=_count_criteria(template.criteria),
                is_shared=template.is_shared,
                data_ins=template.data_ins,
                data_mod=template.data_mod,
                scope_preview=scope_preview,
            )
        )

    return result


@router.get("/{template_id}", response_model=FilterTemplateResponse)
def get_filter_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    template = _get_filter_template_or_404(db, template_id)

    if template.inventory_id:
        inventory = _get_inventory_or_404(db, template.inventory_id)
        if not can_access_inventory(user, inventory, action="view"):
            raise HTTPException(status_code=403, detail="Accesso negato")

    if (
        user.role.name == RoleEnum.admin.value
        or template.user_ins == user.id
        or template.is_shared
    ):
        if isinstance(template.criteria, dict) and template.criteria.get("version") == 2:
            raise HTTPException(409, "Filtro generico: utilizzare /filters")
        return template

    raise HTTPException(status_code=403, detail="Accesso negato")


@router.post("", response_model=FilterTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_filter_template(
    payload: FilterTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.name or not payload.name.strip():
        raise HTTPException(status_code=400, detail="Il nome del template non può essere vuoto")

    existing = db.query(FilterTemplate).filter(
        FilterTemplate.user_ins == user.id,
        FilterTemplate.name == payload.name.strip(),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Esiste già un template con questo nome")

    template = FilterTemplate(
        inventory_id=None,
        name=payload.name.strip(),
        description=payload.description,
        filter_type=payload.filter_type,
        criteria=payload.criteria,
        is_shared=payload.is_shared,
        user_ins=user.id,
        user_mod=user.id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.patch("/{template_id}", response_model=FilterTemplateResponse)
def update_filter_template(
    template_id: int,
    payload: FilterTemplateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    template = _get_filter_template_or_404(db, template_id)
    if template.user_ins != user.id and user.role.name != RoleEnum.admin.value:
        raise HTTPException(status_code=403, detail="Accesso negato")
    if isinstance(template.criteria, dict) and template.criteria.get("version") == 2:
        raise HTTPException(409, "Filtro generico: utilizzare /filters")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"]:
        updates["name"] = updates["name"].strip()
        duplicate = db.query(FilterTemplate).filter(
            FilterTemplate.user_ins == user.id,
            FilterTemplate.name == updates["name"],
            FilterTemplate.id != template.id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="Esiste già un template con questo nome")

    for field, value in updates.items():
        setattr(template, field, value)

    template.user_mod = user.id
    from trigger_service import invalidate_filter_triggers
    invalidate_filter_triggers(db, template.id)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}")
def delete_filter_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    template = _get_filter_template_or_404(db, template_id)
    if template.user_ins != user.id and user.role.name != RoleEnum.admin.value:
        raise HTTPException(status_code=403, detail="Accesso negato")

    from trigger_service import delete_filter_triggers
    delete_filter_triggers(db, template.id)
    db.delete(template)
    db.commit()
    return {"detail": "Template filtro eliminato"}
