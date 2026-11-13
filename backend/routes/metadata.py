from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, cast
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from dependencies import get_db
from metadata_model import (
    InventoryContainerType,
    MetadataDefinitionScope,
    MetadataFieldType,
    MetadataFilterOperator,
    get_value_column_for_type,
)
from models import Inventory, Item, ItemMetadataValue, MetadataDefinition, MetadataDefinitionAssignment, RoleEnum, User
from notification_service import emit_item_updated
from routes.auth import get_current_user
from routes.item import _snapshot_item, _write_item_version
from routes.inventory import can_access_inventory
from schemas import (
    BooleanMetadataFilterCriterion,
    BooleanMetadataFilterRequest,
    BooleanMetadataFilterResponse,
    DateMetadataFilterCriterion,
    DateMetadataFilterRequest,
    DateMetadataFilterResponse,
    ItemMetadataBulkUpsertRequest,
    ItemMetadataValueCreate,
    ItemMetadataValueResponse,
    ItemMetadataValueUpdate,
    ItemMetadataValueUpsert,
    MetadataAssignmentCreate,
    MetadataAssignmentResponse,
    MetadataDefinitionCreate,
    MetadataDefinitionResponse,
    MetadataDefinitionUpdate,
    NumericMetadataFilterCriterion,
    NumericMetadataFilterRequest,
    NumericMetadataFilterResponse,
    TextMetadataFilterCriterion,
    TextMetadataFilterRequest,
    TextMetadataFilterResponse,
)


router = APIRouter()
METADATA_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")
SCOPE_PRIORITY = {
    MetadataDefinitionScope.GLOBAL: 0,
    MetadataDefinitionScope.INVENTORY_TYPE: 1,
    MetadataDefinitionScope.INVENTORY: 2,
}


# ---------------------------------------------------------------------------
# Helpers – risorse
# ---------------------------------------------------------------------------

def _get_inventory_or_404(db: Session, inventory_id: Any) -> Inventory:
    obj = db.query(Inventory).filter(Inventory.id == cast(int, inventory_id)).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Inventario non trovato")
    return obj


def _get_definition_or_404(db: Session, definition_id: Any) -> MetadataDefinition:
    obj = db.query(MetadataDefinition).filter(MetadataDefinition.id == cast(int, definition_id)).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Definizione metadato non trovata")
    return obj


def _get_assignment_or_404(db: Session, assignment_id: int) -> MetadataDefinitionAssignment:
    obj = db.query(MetadataDefinitionAssignment).filter(
        MetadataDefinitionAssignment.id == assignment_id
    ).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Assegnazione metadato non trovata")
    return obj


def _get_item_or_404(db: Session, item_id: Any) -> Item:
    obj = db.query(Item).filter(Item.id == cast(int, item_id)).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Item non trovato")
    return obj


def _to_jsonable_metadata_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _get_value_or_404(db: Session, value_id: Any) -> ItemMetadataValue:
    obj = db.query(ItemMetadataValue).filter(ItemMetadataValue.id == cast(int, value_id)).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Valore metadato non trovato")
    return obj


# ---------------------------------------------------------------------------
# Helpers – autorizzazione
# ---------------------------------------------------------------------------

def _require_admin(user: User) -> None:
    if user.role.name != RoleEnum.admin.value:
        raise HTTPException(status_code=403, detail="Operazione consentita solo agli amministratori")


def _assert_can_manage_assignment(
    user: User,
    db: Session,
    payload: MetadataAssignmentCreate,
) -> Inventory | None:
    # Per scope INVENTORY basta avere accesso edit all'inventario; altrimenti serve admin.
    if payload.scope == MetadataDefinitionScope.INVENTORY:
        if payload.inventory_id is None:
            raise HTTPException(status_code=400, detail="inventory_id obbligatorio per scope INVENTORY")
        inventory = _get_inventory_or_404(db, payload.inventory_id)
        if not can_access_inventory(user, inventory, action="edit"):
            raise HTTPException(status_code=403, detail="Accesso negato")
        return inventory
    _require_admin(user)
    return None


# ---------------------------------------------------------------------------
# Helpers – validazione definizioni
# ---------------------------------------------------------------------------

def _normalize_list_options(raw_options: Any) -> list[dict[str, str]]:
    if raw_options in (None, ""):
        return []

    normalized: list[dict[str, str]] = []
    seen_values: set[str] = set()
    for entry in raw_options:
        if isinstance(entry, dict):
            value = str(entry.get("value", "")).strip()
            label = str(entry.get("label", "")).strip() or value
        else:
            value = str(getattr(entry, "value", "")).strip()
            label = str(getattr(entry, "label", "")).strip() or value

        if not value:
            raise HTTPException(status_code=400, detail="Le opzioni LIST devono avere un valore non vuoto")
        if value in seen_values:
            raise HTTPException(status_code=400, detail=f"Opzione LIST duplicata non consentita: {value}")

        seen_values.add(value)
        normalized.append({"value": value, "label": label})

    return normalized


def _validate_definition_rules(
    key: str | None = None,
    sort_order: int | None = None,
    field_type: MetadataFieldType | None = None,
    list_options: Any = None,
) -> list[dict[str, str]] | None:
    if key is not None:
        normalized = key.strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="La chiave metadato non può essere vuota")
        if not METADATA_KEY_PATTERN.match(normalized):
            raise HTTPException(
                status_code=400,
                detail="Chiave metadato non valida: usa solo lettere, numeri, underscore, punto o trattino",
            )
    if sort_order is not None and sort_order < 0:
        raise HTTPException(status_code=400, detail="sort_order deve essere >= 0")

    if field_type == MetadataFieldType.LIST:
        normalized_list_options = _normalize_list_options(list_options)
        if not normalized_list_options:
            raise HTTPException(status_code=400, detail="Per il tipo LIST è obbligatoria almeno un'opzione")
        return normalized_list_options

    if list_options is not None:
        normalized_list_options = _normalize_list_options(list_options)
        if normalized_list_options:
            raise HTTPException(status_code=400, detail="list_options è consentito solo per field_type=LIST")
        return []

    return None


# ---------------------------------------------------------------------------
# Helpers – risoluzione definizioni applicabili
# ---------------------------------------------------------------------------

def _resolve_applicable_definitions(
    db: Session,
    inventory: Inventory,
    include_inactive: bool = False,
) -> list[MetadataDefinition]:
    # Restituisce le definizioni applicabili a un inventario con priorita' GLOBAL < TYPE < INVENTORY.
    raw_pairs = (
        db.query(MetadataDefinition, MetadataDefinitionAssignment)
        .join(MetadataDefinitionAssignment, MetadataDefinitionAssignment.definition_id == MetadataDefinition.id)
        .filter(
            or_(
                MetadataDefinitionAssignment.scope == MetadataDefinitionScope.GLOBAL.value,
                and_(
                    MetadataDefinitionAssignment.scope == MetadataDefinitionScope.INVENTORY_TYPE.value,
                    MetadataDefinitionAssignment.inventory_type == inventory.type,
                ),
                and_(
                    MetadataDefinitionAssignment.scope == MetadataDefinitionScope.INVENTORY.value,
                    MetadataDefinitionAssignment.inventory_id == inventory.id,
                ),
            )
        )
        .all()
    )
    pairs: list[tuple[MetadataDefinition, MetadataDefinitionAssignment]] = [
        (cast(MetadataDefinition, d), cast(MetadataDefinitionAssignment, a))
        for d, a in raw_pairs
    ]
    if not include_inactive:
        pairs = [(d, a) for d, a in pairs if cast(bool, d.is_active)]

    # Ordina per priorità crescente; l'ultimo valore per chiave vince (più specifico)
    pairs_sorted = sorted(
        pairs,
        key=lambda pair: SCOPE_PRIORITY.get(MetadataDefinitionScope(cast(str, pair[1].scope)), 0),
    )
    by_key: dict[str, MetadataDefinition] = {}
    for definition, _assignment in pairs_sorted:
        by_key[cast(str, definition.key)] = definition
    return sorted(by_key.values(), key=lambda d: (cast(int, d.sort_order), cast(int, d.id)))


def _definition_applies_to_inventory(
    db: Session, inventory: Inventory, definition: MetadataDefinition
) -> bool:
    return db.query(
        db.query(MetadataDefinitionAssignment)
        .filter(
            MetadataDefinitionAssignment.definition_id == definition.id,
            or_(
                MetadataDefinitionAssignment.scope == MetadataDefinitionScope.GLOBAL.value,
                and_(
                    MetadataDefinitionAssignment.scope == MetadataDefinitionScope.INVENTORY_TYPE.value,
                    MetadataDefinitionAssignment.inventory_type == inventory.type,
                ),
                and_(
                    MetadataDefinitionAssignment.scope == MetadataDefinitionScope.INVENTORY.value,
                    MetadataDefinitionAssignment.inventory_id == inventory.id,
                ),
            ),
        )
        .exists()
    ).scalar()


# ---------------------------------------------------------------------------
# Helpers – valori typed
# ---------------------------------------------------------------------------

def _coerce_field_type(definition: MetadataDefinition) -> MetadataFieldType:
    try:
        return MetadataFieldType(definition.field_type)
    except ValueError:
        raise HTTPException(status_code=500, detail="Tipo campo non supportato")


def _extract_typed_values(
    payload: ItemMetadataValueCreate | ItemMetadataValueUpdate | ItemMetadataValueUpsert,
) -> dict:
    data = payload.model_dump()
    return {
        "value_text": data.get("value_text"),
        "value_number": data.get("value_number"),
        "value_boolean": data.get("value_boolean"),
        "value_date": data.get("value_date"),
    }


def _apply_typed_values(value: ItemMetadataValue, typed_values: dict) -> None:
    value.value_text = typed_values["value_text"]
    value.value_number = typed_values["value_number"]
    value.value_boolean = typed_values["value_boolean"]
    value.value_date = typed_values["value_date"]


def _assert_typed_values_match_definition(definition: MetadataDefinition, typed_values: dict) -> None:
    field_type = _coerce_field_type(definition)
    expected_column = get_value_column_for_type(field_type)
    set_columns = [c for c, v in typed_values.items() if v is not None]
    if len(set_columns) != 1:
        raise HTTPException(status_code=400, detail="Esattamente un valore typed deve essere valorizzato")
    if set_columns[0] != expected_column:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo valore non coerente: atteso {field_type.value} ({expected_column})",
        )
    if expected_column == "value_text" and isinstance(typed_values["value_text"], str):
        typed_values["value_text"] = typed_values["value_text"].strip()
        if not typed_values["value_text"]:
            raise HTTPException(status_code=400, detail="Il valore text non può essere vuoto")
        if field_type == MetadataFieldType.LIST:
            allowed_values = {entry["value"] for entry in _normalize_list_options(definition.list_options)}
            if not allowed_values:
                raise HTTPException(status_code=400, detail="Definizione LIST senza opzioni configurate")
            if typed_values["value_text"] not in allowed_values:
                raise HTTPException(status_code=400, detail="Valore non consentito per questo campo LIST")


def _assert_definition_is_active(definition: MetadataDefinition) -> None:
    if not cast(bool, definition.is_active):
        raise HTTPException(status_code=400, detail="Definizione metadato inattiva")


def _to_value_response(
    value: ItemMetadataValue, definition: MetadataDefinition
) -> ItemMetadataValueResponse:
    definition_field_type = cast(str, definition.field_type)
    stored_value_text = cast(str | None, value.value_text)
    display_value: str | None = None
    if definition_field_type == MetadataFieldType.LIST.value and stored_value_text is not None:
        display_value = next(
            (
                entry["label"]
                for entry in _normalize_list_options(definition.list_options)
                if entry["value"] == stored_value_text
            ),
            stored_value_text,
        )

    return ItemMetadataValueResponse(
        id=cast(int, value.id),
        item_id=cast(int, value.item_id),
        definition_id=cast(int, value.definition_id),
        value_text=stored_value_text,
        value_number=cast(Decimal | None, value.value_number),
        value_boolean=cast(bool | None, value.value_boolean),
        value_date=cast(date | None, value.value_date),
        data_ins=cast(datetime, value.data_ins),
        data_mod=cast(datetime, value.data_mod),
        user_ins=cast(int | None, value.user_ins),
        user_mod=cast(int | None, value.user_mod),
        definition_key=cast(str, definition.key),
        definition_label=cast(str, definition.label),
        field_type=MetadataFieldType(definition_field_type),
        display_value=display_value,
    )


def _snapshot_metadata_value(value: ItemMetadataValue | None) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = {
        "value_text": value.value_text,
        "value_number": value.value_number,
        "value_boolean": value.value_boolean,
        "value_date": value.value_date,
    }
    return {key: _to_jsonable_metadata_value(entry) for key, entry in payload.items() if entry is not None}


def _snapshot_typed_values(typed_values: dict[str, Any]) -> dict[str, Any] | None:
    payload = {
        key: _to_jsonable_metadata_value(value)
        for key, value in typed_values.items()
        if value is not None
    }
    return payload or None


def _metadata_values_equal(before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    if before == after:
        return True
    if before is None or after is None:
        return False
    if set(before) == set(after) == {"value_number"}:
        return Decimal(before["value_number"]) == Decimal(after["value_number"])
    return False


def _touch_item_for_metadata_change(
    db: Session,
    item: Item,
    inventory: Inventory,
    user: User,
    metadata_changes: list[dict[str, Any]],
) -> None:
    if not metadata_changes:
        return
    old_snapshot = _snapshot_item(item)
    now = datetime.now(timezone.utc)
    item.user_mod = user.id
    item.data_mod = now
    inventory.user_mod = user.id
    inventory.data_mod = now
    _write_item_version(
        db,
        item,
        "UPDATE",
        user,
        old_snapshot=old_snapshot,
        merge_quantity_updates=False,
        extra_diff={"metadata": metadata_changes},
    )


def _metadata_schema_state(db: Session) -> dict[int, tuple]:
    """Capture effective shared metadata, not audit timestamps or redundant scopes."""
    result = {}
    for item in db.query(Item).all():
        definitions = _resolve_applicable_definitions(db, item.inventory)
        schema = tuple(sorted(
            (definition.id, definition.key, definition.label, definition.description,
             definition.field_type, repr(definition.list_options), definition.sort_order,
             definition.is_required)
            for definition in definitions
        ))
        values = tuple(
            (value.definition_id, repr(_snapshot_metadata_value(value)),
             value.definition.key, value.definition.label, value.definition.field_type,
             repr(value.definition.list_options))
            for value in db.query(ItemMetadataValue).filter(
                ItemMetadataValue.item_id == item.id,
            ).order_by(ItemMetadataValue.definition_id).all()
        )
        result[item.id] = (schema, values)
    return result


def _notify_metadata_schema_change(db: Session, before: dict[int, tuple], user: User) -> None:
    db.flush()
    after = _metadata_schema_state(db)
    for item_id, state in before.items():
        if after.get(item_id) != state:
            item = db.get(Item, item_id)
            if item is not None:
                emit_item_updated(db, item, ["metadata"], user.id)


# ---------------------------------------------------------------------------
# Helpers – predicati filtri avanzati
# ---------------------------------------------------------------------------

def _build_text_metadata_predicate(
    db: Session,
    criterion: TextMetadataFilterCriterion,
    definition: MetadataDefinition,
):
    field_type = MetadataFieldType(definition.field_type)
    if field_type not in {MetadataFieldType.TEXT, MetadataFieldType.LIST}:
        raise HTTPException(status_code=400, detail=f"La definizione {definition.id} non è di tipo TEXT/LIST")

    row_exists = db.query(ItemMetadataValue.id).filter(
        ItemMetadataValue.item_id == Item.id,
        ItemMetadataValue.definition_id == criterion.definition_id,
    ).exists()
    predicate = [
        ItemMetadataValue.item_id == Item.id,
        ItemMetadataValue.definition_id == criterion.definition_id,
    ]
    op = criterion.operator

    if op == MetadataFilterOperator.IS_NULL:
        return ~row_exists
    elif op == MetadataFilterOperator.IS_NOT_NULL:
        return row_exists
    else:
        predicate.append(ItemMetadataValue.value_text.is_not(None))
        if field_type == MetadataFieldType.LIST and op in {
            MetadataFilterOperator.CONTAINS,
            MetadataFilterOperator.NOT_CONTAINS,
        }:
            raise HTTPException(status_code=400, detail="L'operatore scelto non è supportato per il tipo LIST")

        if op == MetadataFilterOperator.EQUALS:
            predicate.append(ItemMetadataValue.value_text == criterion.value_text)
        elif op == MetadataFilterOperator.NOT_EQUALS:
            predicate.append(ItemMetadataValue.value_text != criterion.value_text)
        elif op == MetadataFilterOperator.CONTAINS:
            predicate.append(ItemMetadataValue.value_text.ilike(f"%{criterion.value_text}%"))
        elif op == MetadataFilterOperator.NOT_CONTAINS:
            predicate.append(~ItemMetadataValue.value_text.ilike(f"%{criterion.value_text}%"))
        else:
            raise HTTPException(status_code=400, detail=f"Operatore non supportato: {op.value}")

    return db.query(ItemMetadataValue.id).filter(and_(*predicate)).exists()


def _build_numeric_metadata_predicate(
    db: Session,
    criterion: NumericMetadataFilterCriterion,
    definition: MetadataDefinition,
):
    if MetadataFieldType(definition.field_type) != MetadataFieldType.NUMBER:
        raise HTTPException(status_code=400, detail=f"La definizione {definition.id} non è di tipo NUMBER")
    row_exists = db.query(ItemMetadataValue.id).filter(
        ItemMetadataValue.item_id == Item.id,
        ItemMetadataValue.definition_id == criterion.definition_id,
    ).exists()
    predicate = [
        ItemMetadataValue.item_id == Item.id,
        ItemMetadataValue.definition_id == criterion.definition_id,
    ]
    op = criterion.operator
    if op == MetadataFilterOperator.IS_NULL:
        return ~row_exists
    elif op == MetadataFilterOperator.IS_NOT_NULL:
        return row_exists
    else:
        predicate.append(ItemMetadataValue.value_number.is_not(None))
        if op == MetadataFilterOperator.EQUALS:
            predicate.append(ItemMetadataValue.value_number == criterion.value_number)
        elif op == MetadataFilterOperator.NOT_EQUALS:
            predicate.append(ItemMetadataValue.value_number != criterion.value_number)
        elif op == MetadataFilterOperator.GREATER_THAN:
            predicate.append(ItemMetadataValue.value_number > criterion.value_number)
        elif op == MetadataFilterOperator.GREATER_THAN_OR_EQUAL:
            predicate.append(ItemMetadataValue.value_number >= criterion.value_number)
        elif op == MetadataFilterOperator.LESS_THAN:
            predicate.append(ItemMetadataValue.value_number < criterion.value_number)
        elif op == MetadataFilterOperator.LESS_THAN_OR_EQUAL:
            predicate.append(ItemMetadataValue.value_number <= criterion.value_number)
        elif op == MetadataFilterOperator.BETWEEN:
            predicate.append(ItemMetadataValue.value_number.between(criterion.range_from, criterion.range_to))
        else:
            raise HTTPException(status_code=400, detail=f"Operatore non supportato: {op.value}")
    return db.query(ItemMetadataValue.id).filter(and_(*predicate)).exists()


def _build_date_metadata_predicate(
    db: Session,
    criterion: DateMetadataFilterCriterion,
    definition: MetadataDefinition,
):
    if MetadataFieldType(definition.field_type) != MetadataFieldType.DATE:
        raise HTTPException(status_code=400, detail=f"La definizione {definition.id} non è di tipo DATE")
    row_exists = db.query(ItemMetadataValue.id).filter(
        ItemMetadataValue.item_id == Item.id,
        ItemMetadataValue.definition_id == criterion.definition_id,
    ).exists()
    predicate = [
        ItemMetadataValue.item_id == Item.id,
        ItemMetadataValue.definition_id == criterion.definition_id,
    ]
    op = criterion.operator
    if op == MetadataFilterOperator.IS_NULL:
        return ~row_exists
    elif op == MetadataFilterOperator.IS_NOT_NULL:
        return row_exists
    else:
        predicate.append(ItemMetadataValue.value_date.is_not(None))
        if op == MetadataFilterOperator.EQUALS:
            predicate.append(ItemMetadataValue.value_date == criterion.value_date)
        elif op == MetadataFilterOperator.NOT_EQUALS:
            predicate.append(ItemMetadataValue.value_date != criterion.value_date)
        elif op == MetadataFilterOperator.GREATER_THAN:
            predicate.append(ItemMetadataValue.value_date > criterion.value_date)
        elif op == MetadataFilterOperator.GREATER_THAN_OR_EQUAL:
            predicate.append(ItemMetadataValue.value_date >= criterion.value_date)
        elif op == MetadataFilterOperator.LESS_THAN:
            predicate.append(ItemMetadataValue.value_date < criterion.value_date)
        elif op == MetadataFilterOperator.LESS_THAN_OR_EQUAL:
            predicate.append(ItemMetadataValue.value_date <= criterion.value_date)
        elif op == MetadataFilterOperator.BETWEEN:
            predicate.append(ItemMetadataValue.value_date.between(criterion.range_from, criterion.range_to))
        else:
            raise HTTPException(status_code=400, detail=f"Operatore non supportato: {op.value}")
    return db.query(ItemMetadataValue.id).filter(and_(*predicate)).exists()


# ===========================================================================
# ROUTES – Filtri avanzati
# ===========================================================================

@router.post("/filters/text", response_model=TextMetadataFilterResponse)
def filter_items_by_text_metadata(
    payload: TextMetadataFilterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inventory = _get_inventory_or_404(db, payload.inventory_id)
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    definition_ids = {c.definition_id for c in payload.criteria}
    definitions = {
        cast(int, d.id): d
        for d in _resolve_applicable_definitions(db, inventory)
        if cast(int, d.id) in definition_ids
    }
    if len(definitions) != len(definition_ids):
        raise HTTPException(
            status_code=400,
            detail="Una o più definizioni non sono valide per questo inventario o risultano inattive",
        )
    exists_predicates = [
        _build_text_metadata_predicate(db, c, definitions[c.definition_id]) for c in payload.criteria
    ]
    query = db.query(Item.id).filter(Item.inventory_id == payload.inventory_id)
    if payload.match_mode == "all":
        query = query.filter(and_(*exists_predicates))
    else:
        query = query.filter(or_(*exists_predicates))
    item_ids = [r[0] for r in query.order_by(Item.id.asc()).all()]
    return TextMetadataFilterResponse(
        inventory_id=payload.inventory_id,
        match_mode=payload.match_mode,
        item_ids=item_ids,
        count=len(item_ids),
    )


@router.post("/filters/numeric", response_model=NumericMetadataFilterResponse)
def filter_items_by_numeric_metadata(
    payload: NumericMetadataFilterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inventory = _get_inventory_or_404(db, payload.inventory_id)
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    definition_ids = {c.definition_id for c in payload.criteria}
    definitions = {
        cast(int, d.id): d
        for d in _resolve_applicable_definitions(db, inventory)
        if cast(int, d.id) in definition_ids
    }
    if len(definitions) != len(definition_ids):
        raise HTTPException(
            status_code=400,
            detail="Una o più definizioni non sono valide per questo inventario o risultano inattive",
        )
    exists_predicates = [
        _build_numeric_metadata_predicate(db, c, definitions[c.definition_id]) for c in payload.criteria
    ]
    query = db.query(Item.id).filter(Item.inventory_id == payload.inventory_id)
    if payload.match_mode == "all":
        query = query.filter(and_(*exists_predicates))
    else:
        query = query.filter(or_(*exists_predicates))
    item_ids = [r[0] for r in query.order_by(Item.id.asc()).all()]
    return NumericMetadataFilterResponse(
        inventory_id=payload.inventory_id,
        match_mode=payload.match_mode,
        item_ids=item_ids,
        count=len(item_ids),
    )


@router.post("/filters/date", response_model=DateMetadataFilterResponse)
def filter_items_by_date_metadata(
    payload: DateMetadataFilterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inventory = _get_inventory_or_404(db, payload.inventory_id)
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    definition_ids = {c.definition_id for c in payload.criteria}
    definitions = {
        cast(int, d.id): d
        for d in _resolve_applicable_definitions(db, inventory)
        if cast(int, d.id) in definition_ids
    }
    if len(definitions) != len(definition_ids):
        raise HTTPException(
            status_code=400,
            detail="Una o più definizioni non sono valide per questo inventario o risultano inattive",
        )
    exists_predicates = [
        _build_date_metadata_predicate(db, c, definitions[c.definition_id]) for c in payload.criteria
    ]
    query = db.query(Item.id).filter(Item.inventory_id == payload.inventory_id)
    if payload.match_mode == "all":
        query = query.filter(and_(*exists_predicates))
    else:
        query = query.filter(or_(*exists_predicates))
    item_ids = [r[0] for r in query.order_by(Item.id.asc()).all()]
    return DateMetadataFilterResponse(
        inventory_id=payload.inventory_id,
        match_mode=payload.match_mode,
        item_ids=item_ids,
        count=len(item_ids),
    )


def _build_boolean_metadata_predicate(
    db: Session,
    criterion: BooleanMetadataFilterCriterion,
    definition: MetadataDefinition,
):
    if MetadataFieldType(definition.field_type) != MetadataFieldType.BOOLEAN:
        raise HTTPException(status_code=400, detail=f"La definizione {definition.id} non è di tipo BOOLEAN")
    row_exists = db.query(ItemMetadataValue.id).filter(
        ItemMetadataValue.item_id == Item.id,
        ItemMetadataValue.definition_id == criterion.definition_id,
    ).exists()
    predicate = [
        ItemMetadataValue.item_id == Item.id,
        ItemMetadataValue.definition_id == criterion.definition_id,
    ]
    op = criterion.operator
    if op == MetadataFilterOperator.IS_NULL:
        return ~row_exists
    elif op == MetadataFilterOperator.IS_NOT_NULL:
        return row_exists
    elif op == MetadataFilterOperator.EQUALS:
        predicate.append(ItemMetadataValue.value_boolean.is_not(None))
        predicate.append(ItemMetadataValue.value_boolean == criterion.value_boolean)
    elif op == MetadataFilterOperator.NOT_EQUALS:
        predicate.append(ItemMetadataValue.value_boolean.is_not(None))
        predicate.append(ItemMetadataValue.value_boolean != criterion.value_boolean)
    else:
        raise HTTPException(status_code=400, detail=f"Operatore non supportato: {op.value}")
    return db.query(ItemMetadataValue.id).filter(and_(*predicate)).exists()


@router.post("/filters/boolean", response_model=BooleanMetadataFilterResponse)
def filter_items_by_boolean_metadata(
    payload: BooleanMetadataFilterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inventory = _get_inventory_or_404(db, payload.inventory_id)
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    definition_ids = {c.definition_id for c in payload.criteria}
    definitions = {
        cast(int, d.id): d
        for d in _resolve_applicable_definitions(db, inventory)
        if cast(int, d.id) in definition_ids
    }
    if len(definitions) != len(definition_ids):
        raise HTTPException(
            status_code=400,
            detail="Una o più definizioni non sono valide per questo inventario o risultano inattive",
        )
    exists_predicates = [
        _build_boolean_metadata_predicate(db, c, definitions[c.definition_id]) for c in payload.criteria
    ]
    query = db.query(Item.id).filter(Item.inventory_id == payload.inventory_id)
    if payload.match_mode == "all":
        query = query.filter(and_(*exists_predicates))
    else:
        query = query.filter(or_(*exists_predicates))
    item_ids = [r[0] for r in query.order_by(Item.id.asc()).all()]
    return BooleanMetadataFilterResponse(
        inventory_id=payload.inventory_id,
        match_mode=payload.match_mode,
        item_ids=item_ids,
        count=len(item_ids),
    )


# ===========================================================================
# ROUTES – Definizioni metadato (solo admin)
# ===========================================================================

@router.get("/definitions", response_model=List[MetadataDefinitionResponse])
def list_metadata_definitions(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Elenca le definizioni metadato. Admin vede tutte; gli altri vedono solo quelle attive."""
    from models import RoleEnum
    query = db.query(MetadataDefinition)
    if user.role.name != RoleEnum.admin.value:
        query = query.filter(MetadataDefinition.is_active.is_(True))
    elif not include_inactive:
        query = query.filter(MetadataDefinition.is_active.is_(True))
    return query.order_by(MetadataDefinition.sort_order.asc(), MetadataDefinition.id.asc()).all()


@router.get("/applicable", response_model=List[MetadataDefinitionResponse])
def list_applicable_definitions(
    inventory_id: int = Query(..., gt=0),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Definizioni applicabili a un inventario (merge GLOBAL+TYPE+INVENTORY), usato dalla detail page."""
    inventory = _get_inventory_or_404(db, inventory_id)
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    # Security: Defense-in-depth to prevent leaking inactive metadata definitions to non-admin users.
    # Non-admin users are restricted to active definitions, matching GET /metadata/definitions behavior.
    effective_include_inactive = include_inactive if user.role.name == RoleEnum.admin.value else False
    return _resolve_applicable_definitions(db, inventory, include_inactive=effective_include_inactive)


@router.get("/definitions/{definition_id}", response_model=MetadataDefinitionResponse)
def get_metadata_definition(
    definition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)
    return _get_definition_or_404(db, definition_id)


@router.post("/definitions", response_model=MetadataDefinitionResponse, status_code=status.HTTP_201_CREATED)
def create_metadata_definition(
    payload: MetadataDefinitionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)
    normalized_list_options = _validate_definition_rules(
        key=payload.key,
        sort_order=payload.sort_order,
        field_type=payload.field_type,
        list_options=payload.list_options,
    )
    payload.key = payload.key.strip()
    if db.query(MetadataDefinition).filter(MetadataDefinition.key == payload.key).first():
        raise HTTPException(status_code=409, detail="Chiave metadato già esistente")
    payload_data = payload.model_dump()
    payload_data["list_options"] = normalized_list_options if payload.field_type == MetadataFieldType.LIST else None
    definition = MetadataDefinition(**payload_data)
    definition.user_ins = user.id
    definition.user_mod = user.id
    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition


@router.patch("/definitions/{definition_id}", response_model=MetadataDefinitionResponse)
def update_metadata_definition(
    definition_id: int,
    payload: MetadataDefinitionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)
    definition = _get_definition_or_404(db, definition_id)
    updates = payload.model_dump(exclude_unset=True)
    _validate_definition_rules(key=updates.get("key"), sort_order=updates.get("sort_order"))
    if "list_options" in updates:
        current_field_type = _coerce_field_type(definition)
        normalized_list_options = _validate_definition_rules(
            field_type=current_field_type,
            list_options=updates.get("list_options"),
        )
        updates["list_options"] = normalized_list_options if current_field_type == MetadataFieldType.LIST else None
    if "key" in updates:
        updates["key"] = updates["key"].strip()
        if db.query(MetadataDefinition).filter(
            MetadataDefinition.key == updates["key"],
            MetadataDefinition.id != definition_id,
        ).first():
            raise HTTPException(status_code=409, detail="Chiave metadato già esistente")
    before = _metadata_schema_state(db)
    for field, value in updates.items():
        setattr(definition, field, value)
    definition.user_mod = user.id
    _notify_metadata_schema_change(db, before, user)
    db.commit()
    db.refresh(definition)
    return definition


@router.delete("/definitions/{definition_id}")
def delete_metadata_definition(
    definition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)
    definition = _get_definition_or_404(db, definition_id)
    before = _metadata_schema_state(db)
    db.delete(definition)
    _notify_metadata_schema_change(db, before, user)
    db.commit()
    return {"detail": "Definizione metadato eliminata"}


# ===========================================================================
# ROUTES – Assegnazioni
# ===========================================================================

@router.get("/definitions/{definition_id}/assignments", response_model=List[MetadataAssignmentResponse])
def list_metadata_assignments(
    definition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_admin(user)
    _get_definition_or_404(db, definition_id)
    return (
        db.query(MetadataDefinitionAssignment)
        .filter(MetadataDefinitionAssignment.definition_id == definition_id)
        .order_by(MetadataDefinitionAssignment.id.asc())
        .all()
    )


@router.post(
    "/definitions/{definition_id}/assignments",
    response_model=MetadataAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_metadata_assignment(
    definition_id: int,
    payload: MetadataAssignmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_definition_or_404(db, definition_id)
    _assert_can_manage_assignment(user, db, payload)

    dup_q = db.query(MetadataDefinitionAssignment).filter(
        MetadataDefinitionAssignment.definition_id == definition_id,
        MetadataDefinitionAssignment.scope == payload.scope.value,
    )
    if payload.scope == MetadataDefinitionScope.INVENTORY_TYPE:
        if payload.inventory_type is None:
            raise HTTPException(status_code=400, detail="inventory_type obbligatorio per scope INVENTORY_TYPE")
        dup_q = dup_q.filter(MetadataDefinitionAssignment.inventory_type == payload.inventory_type.value)
    elif payload.scope == MetadataDefinitionScope.INVENTORY:
        dup_q = dup_q.filter(MetadataDefinitionAssignment.inventory_id == payload.inventory_id)
    if dup_q.first():
        raise HTTPException(status_code=409, detail="Assegnazione già presente per questo scope")

    before = _metadata_schema_state(db)
    assignment = MetadataDefinitionAssignment(
        definition_id=definition_id,
        scope=payload.scope.value,
        inventory_type=payload.inventory_type.value if payload.inventory_type else None,
        inventory_id=payload.inventory_id,
        user_ins=user.id,
        user_mod=user.id,
    )
    db.add(assignment)
    _notify_metadata_schema_change(db, before, user)
    db.commit()
    db.refresh(assignment)
    return assignment


@router.delete("/assignments/{assignment_id}")
def delete_metadata_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assignment = _get_assignment_or_404(db, assignment_id)
    scope = MetadataDefinitionScope(assignment.scope)
    if scope == MetadataDefinitionScope.INVENTORY:
        inventory_id = cast(int | None, assignment.inventory_id)
        if inventory_id is None:
            raise HTTPException(status_code=400, detail="Assegnazione INVENTORY senza inventory_id")
        inventory = _get_inventory_or_404(db, inventory_id)
        if not can_access_inventory(user, inventory, action="edit"):
            raise HTTPException(status_code=403, detail="Accesso negato")
    else:
        _require_admin(user)
    before = _metadata_schema_state(db)
    db.delete(assignment)
    _notify_metadata_schema_change(db, before, user)
    db.commit()
    return {"detail": "Assegnazione metadato eliminata"}


# ===========================================================================
# ROUTES – Valori metadato su item
# ===========================================================================

@router.get("/values", response_model=List[ItemMetadataValueResponse])
def list_item_metadata_values(
    item_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item_or_404(db, item_id)
    inventory = _get_inventory_or_404(db, item.inventory_id)
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    rows = (
        db.query(ItemMetadataValue, MetadataDefinition)
        .join(MetadataDefinition, MetadataDefinition.id == ItemMetadataValue.definition_id)
        .filter(ItemMetadataValue.item_id == item_id)
        .order_by(MetadataDefinition.sort_order.asc(), MetadataDefinition.id.asc())
        .all()
    )
    return [_to_value_response(v, d) for v, d in rows]


@router.get("/values/{value_id}", response_model=ItemMetadataValueResponse)
def get_item_metadata_value(
    value_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    value = _get_value_or_404(db, value_id)
    item = _get_item_or_404(db, value.item_id)
    inventory = _get_inventory_or_404(db, item.inventory_id)
    if not can_access_inventory(user, inventory, action="view"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    definition = _get_definition_or_404(db, value.definition_id)
    return _to_value_response(value, definition)


@router.post("/values", response_model=ItemMetadataValueResponse, status_code=status.HTTP_201_CREATED)
def create_item_metadata_value(
    payload: ItemMetadataValueCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item_or_404(db, payload.item_id)
    inventory = _get_inventory_or_404(db, item.inventory_id)
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    definition = _get_definition_or_404(db, payload.definition_id)
    if not _definition_applies_to_inventory(db, inventory, definition):
        raise HTTPException(
            status_code=400,
            detail="La definizione metadato non è applicabile all'inventario dell'item",
        )
    _assert_definition_is_active(definition)
    if db.query(ItemMetadataValue).filter(
        ItemMetadataValue.item_id == payload.item_id,
        ItemMetadataValue.definition_id == payload.definition_id,
    ).first():
        raise HTTPException(status_code=409, detail="Valore metadato già presente")
    value = ItemMetadataValue(
        item_id=payload.item_id,
        definition_id=payload.definition_id,
        user_ins=user.id,
        user_mod=user.id,
    )
    typed_values = _extract_typed_values(payload)
    _assert_typed_values_match_definition(definition, typed_values)
    _apply_typed_values(value, typed_values)
    db.add(value)
    db.flush()
    _touch_item_for_metadata_change(
        db,
        item,
        inventory,
        user,
        [{
            "definition_id": definition.id,
            "definition_key": definition.key,
            "definition_label": definition.label,
            "from": None,
            "to": _snapshot_typed_values(typed_values),
        }],
    )
    db.commit()
    db.refresh(value)
    return _to_value_response(value, definition)


@router.patch("/values/{value_id}", response_model=ItemMetadataValueResponse)
def update_item_metadata_value(
    value_id: int,
    payload: ItemMetadataValueUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    value = _get_value_or_404(db, value_id)
    item = _get_item_or_404(db, value.item_id)
    inventory = _get_inventory_or_404(db, item.inventory_id)
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    definition = _get_definition_or_404(db, value.definition_id)
    if not _definition_applies_to_inventory(db, inventory, definition):
        raise HTTPException(
            status_code=400,
            detail="La definizione metadato non è applicabile all'inventario dell'item",
        )
    _assert_definition_is_active(definition)
    before_value = _snapshot_metadata_value(value)
    typed_values = _extract_typed_values(payload)
    _assert_typed_values_match_definition(definition, typed_values)
    _apply_typed_values(value, typed_values)
    value.user_mod = user.id
    after_value = _snapshot_typed_values(typed_values)
    if not _metadata_values_equal(before_value, after_value):
        _touch_item_for_metadata_change(
            db,
            item,
            inventory,
            user,
            [{
                "definition_id": definition.id,
                "definition_key": definition.key,
                "definition_label": definition.label,
                "from": before_value,
                "to": after_value,
            }],
        )
    db.commit()
    db.refresh(value)
    return _to_value_response(value, definition)


@router.delete("/values/{value_id}")
def delete_item_metadata_value(
    value_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    value = _get_value_or_404(db, value_id)
    item = _get_item_or_404(db, value.item_id)
    inventory = _get_inventory_or_404(db, item.inventory_id)
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    definition = _get_definition_or_404(db, value.definition_id)
    if cast(bool, definition.is_required):
        raise HTTPException(status_code=400, detail="Non è possibile eliminare un valore metadato obbligatorio")
    before_value = _snapshot_metadata_value(value)
    db.delete(value)
    _touch_item_for_metadata_change(
        db,
        item,
        inventory,
        user,
        [{
            "definition_id": definition.id,
            "definition_key": definition.key,
            "definition_label": definition.label,
            "from": before_value,
            "to": None,
        }],
    )
    db.commit()
    return {"detail": "Valore metadato eliminato"}


def _upsert_metadata_values(
    db: Session, item: Item, inventory: Inventory, user: User, values: list[ItemMetadataValueUpsert],
) -> tuple[list[ItemMetadataValueResponse], list[dict[str, Any]]]:
    definitions = {
        cast(int, d.id): d for d in _resolve_applicable_definitions(db, inventory, include_inactive=True)
    }
    result: List[ItemMetadataValueResponse] = []
    metadata_changes: list[dict[str, Any]] = []
    for entry in values:
        definition = definitions.get(entry.definition_id)
        if not definition:
            raise HTTPException(
                status_code=400,
                detail=f"Definizione metadato {entry.definition_id} non valida per l'inventario dell'item",
            )
        _assert_definition_is_active(definition)
        value = db.query(ItemMetadataValue).filter(
            ItemMetadataValue.item_id == item.id,
            ItemMetadataValue.definition_id == entry.definition_id,
        ).first()
        before_value = _snapshot_metadata_value(value)
        if not value:
            value = ItemMetadataValue(
                item_id=item.id,
                definition_id=entry.definition_id,
                user_ins=user.id,
                user_mod=user.id,
            )
            db.add(value)
        else:
            value.user_mod = user.id
        typed_values = _extract_typed_values(entry)
        _assert_typed_values_match_definition(definition, typed_values)
        _apply_typed_values(value, typed_values)
        db.flush()
        after_value = _snapshot_typed_values(typed_values)
        if not _metadata_values_equal(before_value, after_value):
            metadata_changes.append({
                "definition_id": definition.id,
                "definition_key": definition.key,
                "definition_label": definition.label,
                "from": before_value,
                "to": after_value,
            })
        result.append(_to_value_response(value, definition))
    return result, metadata_changes


@router.put("/values/bulk-upsert", response_model=List[ItemMetadataValueResponse])
def bulk_upsert_item_metadata_values(
    payload: ItemMetadataBulkUpsertRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item_or_404(db, payload.item_id)
    inventory = _get_inventory_or_404(db, item.inventory_id)
    if not can_access_inventory(user, inventory, action="edit"):
        raise HTTPException(status_code=403, detail="Accesso negato")
    result, metadata_changes = _upsert_metadata_values(db, item, inventory, user, payload.values)
    _touch_item_for_metadata_change(db, item, inventory, user, metadata_changes)
    db.commit()
    return result
