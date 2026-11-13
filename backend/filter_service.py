"""One typed SQL evaluator for previews, persisted filters and scheduled runs."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session, selectinload

from filter_contracts import FilterCondition, FilterInput, RelativeDate, validate_timezone
from metadata_model import MetadataFieldType, get_supported_filter_operators, get_value_column_for_type
from models import (
    FilterTemplate, Inventory, Item, ItemBarcode, ItemMetadataValue,
    MetadataDefinition, MetadataDefinitionAssignment, ScheduledTrigger, User,
)
from notification_outbox import utcnow
from routes.inventory import can_access_inventory

TYPES = ["INVENTORY", "CHECKLIST"]
ITEM_FIELDS = {
    "name": ("Nome", "TEXT", TYPES),
    "description": ("Descrizione", "TEXT", TYPES),
    "quantity": ("Quantità", "NUMBER", ["INVENTORY"]),
    "completed": ("Completato", "BOOLEAN", ["CHECKLIST"]),
    "priority": ("Priorità", "NUMBER", ["CHECKLIST"]),
    "barcode": ("Barcode", "TEXT", TYPES),
    "created_at": ("Creato il", "DATE", TYPES),
    "modified_at": ("Modificato il", "DATE", TYPES),
}
NULL_OPERATORS = ["is_null", "is_not_null"]


def is_admin(user: User) -> bool:
    return user.role is not None and user.role.name == "admin"


def can_manage_filter(user: User, template: FilterTemplate) -> bool:
    return not user.is_blocked and (is_admin(user) or template.user_ins == user.id)


def can_view_filter(db: Session, user: User, template: FilterTemplate) -> bool:
    if user.is_blocked or not (can_manage_filter(user, template) or template.is_shared):
        return False
    if template.inventory_id is not None:
        inventory = db.get(Inventory, template.inventory_id)
        return inventory is not None and can_access_inventory(user, inventory, "view")
    return True


def get_filter(db: Session, user: User, filter_id: int, *, manage: bool = False) -> FilterTemplate:
    template = db.get(FilterTemplate, filter_id)
    if template is None:
        raise HTTPException(404, "Filtro non trovato")
    if not can_view_filter(db, user, template) or manage and not can_manage_filter(user, template):
        raise HTTPException(403, "Accesso negato")
    return template


def visible_inventories(db: Session, user: User, *, action: str = "view") -> list[Inventory]:
    if user.is_blocked or user.role is None:
        return []
    inventories = db.scalars(select(Inventory).options(
        selectinload(Inventory.shared_with_users), selectinload(Inventory.shared_with_groups),
    ).order_by(Inventory.id)).all()
    return [inventory for inventory in inventories if can_access_inventory(user, inventory, action)]


def applicable(definition: MetadataDefinition, inventory: Inventory) -> bool:
    return any(
        assignment.scope == "GLOBAL"
        or assignment.scope == "INVENTORY_TYPE" and assignment.inventory_type == inventory.type
        or assignment.scope == "INVENTORY" and assignment.inventory_id == inventory.id
        for assignment in definition.assignments
    )


def available_types(definition: MetadataDefinition, inventories: list[Inventory]) -> list[str]:
    types = set()
    for assignment in definition.assignments:
        if assignment.scope == "GLOBAL":
            types.update(TYPES)
        elif assignment.scope == "INVENTORY_TYPE":
            types.add(assignment.inventory_type)
        else:
            types.update(inv.type for inv in inventories if inv.id == assignment.inventory_id)
    return sorted(types)


def definitions_for_user(db: Session, user: User) -> dict[int, MetadataDefinition]:
    inventories = visible_inventories(db, user)
    return {
        definition.id: definition
        for definition in db.scalars(select(MetadataDefinition).options(
            selectinload(MetadataDefinition.assignments),
        ).order_by(MetadataDefinition.sort_order, MetadataDefinition.id))
        if is_admin(user) or definition.is_active and any(applicable(definition, inventory) for inventory in inventories)
    }


def operators(field_type: str, *, barcode: bool = False) -> list[str]:
    if barcode:
        return ["contains", *NULL_OPERATORS]
    return [op.value for op in get_supported_filter_operators(MetadataFieldType(field_type))]


def field_catalog(db: Session, user: User) -> list[dict]:
    result = [{
        "source": "item", "field": field, "label": label, "field_type": kind,
        "operators": operators(kind, barcode=field == "barcode"), "container_types": types,
    } for field, (label, kind, types) in ITEM_FIELDS.items()]
    inventories = visible_inventories(db, user)
    for definition in definitions_for_user(db, user).values():
        entry = {
            "source": "metadata", "field": definition.key, "label": definition.label,
            "field_type": definition.field_type, "definition_id": definition.id,
            "operators": operators(definition.field_type),
            "container_types": available_types(definition, inventories),
        }
        if definition.field_type == "LIST":
            entry["list_options"] = definition.list_options or []
        result.append(entry)
    return result


def date_value(value, zone: ZoneInfo, now: datetime) -> date:
    if isinstance(value, RelativeDate):
        current = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
        return current.astimezone(zone).date() + timedelta(days=value.relative_days)
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise HTTPException(422, "Data ISO YYYY-MM-DD o relative_days obbligatoria")


def typed_value(value, kind: str, zone: ZoneInfo, now: datetime):
    if kind == "DATE":
        return date_value(value, zone, now)
    if kind == "NUMBER" and not isinstance(value, (bool, RelativeDate)):
        try:
            number = Decimal(str(value))
            if number.is_finite() and abs(number) <= Decimal("9999999999.9999"):
                return number
        except InvalidOperation:
            pass
    elif kind == "BOOLEAN" and isinstance(value, bool):
        return value
    elif kind in {"TEXT", "LIST"} and isinstance(value, str) and len(value) <= 4000:
        return value
    raise HTTPException(422, f"Valore non valido per {kind}")


def validate_filter(
    db: Session, user: User, payload: FilterInput, *, zone: str = "Europe/Rome",
    now: datetime | None = None,
) -> dict[int, MetadataDefinition]:
    zoneinfo = ZoneInfo(validate_timezone(zone))
    current = now or utcnow()
    definitions = definitions_for_user(db, user)
    for condition in payload.conditions:
        if condition.source == "item":
            if condition.field not in ITEM_FIELDS or condition.definition_id is not None:
                raise HTTPException(422, "Campo elemento non valido")
            _label, kind, types = ITEM_FIELDS[condition.field]
            if payload.container_type is not None and payload.container_type not in types:
                raise HTTPException(422, "Campo non disponibile per questo tipo di contenitore")
        else:
            definition = definitions.get(condition.definition_id)
            if definition is None or definition.key != condition.field:
                raise HTTPException(422, "Metadato inesistente o non visibile")
            kind = definition.field_type
            if payload.container_type is not None:
                inventories = visible_inventories(db, user)
                if payload.container_type not in available_types(definition, inventories):
                    raise HTTPException(422, "Metadato non disponibile per questo tipo di contenitore")
        if condition.operator not in operators(kind, barcode=condition.source == "item" and condition.field == "barcode"):
            raise HTTPException(422, "Operatore non supportato per il tipo di campo")
        if condition.operator in NULL_OPERATORS:
            if any(value is not None for value in (condition.value, condition.range_from, condition.range_to)):
                raise HTTPException(422, "Gli operatori NULL non accettano valori")
            continue
        if condition.operator == "between":
            if condition.value is not None:
                raise HTTPException(422, "between richiede solo gli estremi")
            low = typed_value(condition.range_from, kind, zoneinfo, current)
            high = typed_value(condition.range_to, kind, zoneinfo, current)
            if low > high:
                raise HTTPException(422, "range_from non può superare range_to")
            values = [low, high]
        else:
            if condition.range_from is not None or condition.range_to is not None:
                raise HTTPException(422, "Gli estremi richiedono between")
            value = typed_value(condition.value, kind, zoneinfo, current)
            values = [value]
            if kind == "LIST" and value not in {
                option["value"] for option in definitions[condition.definition_id].list_options or []
            }:
                raise HTTPException(422, "Opzione LIST non valida")
        if condition.source == "item" and kind == "DATE" and any(value.year in (1, 9999) for value in values):
            raise HTTPException(422, "La data non è rappresentabile come intervallo UTC")
    return definitions


def filter_input(db: Session, template: FilterTemplate) -> FilterInput:
    raw = template.criteria
    if isinstance(raw, dict) and raw.get("version") == 2:
        try:
            return FilterInput(
                name=template.name, description=template.description, is_shared=template.is_shared,
                container_type=raw.get("container_type"), match_mode=raw.get("match_mode", "all"),
                conditions=raw["conditions"],
            )
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "Criteri del filtro non validi") from None
    # Legacy records are read through an adapter; the stored criteria and old APIs remain untouched.
    entries = raw.get("criteria", []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise HTTPException(422, "Criteri legacy non validi")
    conditions = []
    for entry in entries:
        if not isinstance(entry, dict) or "operator" not in entry:
            raise HTTPException(422, "Criterio legacy non valido")
        try:
            definition_id = int(entry["definition_id"])
            if isinstance(entry["definition_id"], bool) or definition_id <= 0:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "Criterio legacy non valido") from None
        definition = db.get(MetadataDefinition, definition_id)
        if definition is None:
            raise HTTPException(422, "Filtro legacy con metadato eliminato")
        values = {}
        for key in ("value", "range_from", "range_to"):
            value = entry.get(key)
            if key == "value":
                value = next((entry[name] for name in ("value_text", "value_number", "value_boolean", "value_date")
                              if entry.get(name) is not None), value)
            if definition.field_type in {"TEXT", "LIST"} and isinstance(value, str):
                value = value.strip() or None
            if definition.field_type == "DATE" and isinstance(value, str) and value.strip().lower() in {"today", "oggi"}:
                value = {"relative_days": 0}
            if entry["operator"] in NULL_OPERATORS:
                value = None
            values[key] = value
        try:
            conditions.append(FilterCondition(
                source="metadata", field=definition.key, definition_id=definition.id,
                operator=entry["operator"], **values,
            ))
        except ValueError:
            raise HTTPException(422, "Criterio legacy non valido") from None
    if not conditions:
        raise HTTPException(422, "Filtro legacy senza criteri valutabili")
    try:
        return FilterInput(
            name=template.name, description=template.description, is_shared=template.is_shared,
            match_mode=raw.get("match_mode", "all") if isinstance(raw, dict) else "all",
            conditions=conditions,
        )
    except ValueError:
        raise HTTPException(422, "Criteri legacy non validi") from None


def persist_filter(template: FilterTemplate, payload: FilterInput, user: User) -> None:
    template.name = payload.name
    template.description = payload.description
    template.is_shared = payload.is_shared
    template.filter_type = "composite"
    template.criteria = {
        "version": 2, "container_type": payload.container_type, "match_mode": payload.match_mode,
        "conditions": [condition.model_dump(mode="json") for condition in payload.conditions],
    }
    template.user_mod = user.id


def condition_available(condition: FilterCondition, inventory: Inventory, definitions: dict) -> bool:
    if condition.source == "item":
        return inventory.type in ITEM_FIELDS[condition.field][2]
    return applicable(definitions[condition.definition_id], inventory)


def compatible_inventories(payload: FilterInput, inventories: list[Inventory], definitions: dict) -> list[Inventory]:
    reducer = all if payload.match_mode == "all" else any
    return [inventory for inventory in inventories if (
        payload.container_type is None or inventory.type == payload.container_type
    ) and reducer(condition_available(condition, inventory, definitions) for condition in payload.conditions)]


def scope_preview(payload: FilterInput, inventories: list[Inventory], definitions: dict) -> dict:
    compatible = compatible_inventories(payload, inventories, definitions)
    return {
        "scope_type": "specific" if compatible else "none",
        "summary": f"{len(compatible)} contenitori compatibili",
        "inventories": [{"id": inv.id, "name": inv.name, "type": inv.type} for inv in compatible],
    }


def comparison(column, condition: FilterCondition, kind: str, zone: ZoneInfo, now: datetime, *, timestamp=False, legacy=False):
    op = condition.operator
    if op == "is_null":
        return column.is_(None)
    if op == "is_not_null":
        return column.is_not(None)
    value = typed_value(condition.value, kind, zone, now) if op != "between" else None
    low = typed_value(condition.range_from, kind, zone, now) if op == "between" else None
    high = typed_value(condition.range_to, kind, zone, now) if op == "between" else None
    if timestamp:
        def boundary(day):
            return datetime.combine(day, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
        if op == "between":
            return and_(column >= boundary(low), column < boundary(high + timedelta(days=1)))
        start, end = boundary(value), boundary(value + timedelta(days=1))
        return {
            "equals": and_(column >= start, column < end),
            "not_equals": and_(column.is_not(None), or_(column < start, column >= end)),
            "gt": column >= end, "gte": column >= start, "lt": column < start, "lte": column < end,
        }[op]
    if op == "contains" or op == "not_contains":
        # User text is a literal substring, never a SQL LIKE pattern.
        predicate = column.ilike(f"%{value}%") if legacy else column.icontains(value, autoescape=True)
        return predicate if op == "contains" else and_(column.is_not(None), ~predicate)
    if op == "between":
        return column.between(low, high)
    return {
        "equals": lambda: column == value, "not_equals": lambda: column != value,
        "gt": lambda: column > value, "gte": lambda: column >= value,
        "lt": lambda: column < value, "lte": lambda: column <= value,
    }[op]()


def evaluate_filter(
    db: Session, user: User, payload: FilterInput, *, inventory_ids: list[int] | None = None,
    zone: str = "Europe/Rome", now: datetime | None = None, action: str = "view",
    legacy: bool = False,
) -> dict:
    current = now or utcnow()
    definitions = validate_filter(db, user, payload, zone=zone, now=current)
    inventories = visible_inventories(db, user, action=action)
    if inventory_ids is not None:
        allowed = {inventory.id for inventory in inventories}
        if not set(inventory_ids) <= allowed:
            raise HTTPException(403, "Uno o più contenitori non sono accessibili")
        inventories = [inventory for inventory in inventories if inventory.id in inventory_ids]
    inventories = compatible_inventories(payload, inventories, definitions)
    by_id = {inventory.id: inventory for inventory in inventories}
    predicates = []
    for condition in payload.conditions:
        eligible = [inv.id for inv in inventories if condition_available(condition, inv, definitions)]
        if not eligible:
            predicates.append(false())
            continue
        if condition.source == "metadata":
            definition = definitions[condition.definition_id]
            column = getattr(ItemMetadataValue, get_value_column_for_type(MetadataFieldType(definition.field_type)))
            exists = select(ItemMetadataValue.id).where(
                ItemMetadataValue.item_id == Item.id, ItemMetadataValue.definition_id == definition.id,
                column.is_not(None),
            ).exists()
            if condition.operator == "is_null":
                predicate = ~exists
            elif condition.operator == "is_not_null":
                predicate = exists
            else:
                predicate = select(ItemMetadataValue.id).where(
                    ItemMetadataValue.item_id == Item.id, ItemMetadataValue.definition_id == definition.id,
                    comparison(column, condition, definition.field_type, ZoneInfo(zone), current, legacy=legacy),
                ).exists()
        elif condition.field == "barcode":
            exists = select(ItemBarcode.id).where(ItemBarcode.item_id == Item.id).exists()
            predicate = ~exists if condition.operator == "is_null" else exists
            if condition.operator == "contains":
                predicate = select(ItemBarcode.id).where(
                    ItemBarcode.item_id == Item.id,
                    ItemBarcode.code.icontains(condition.value, autoescape=True),
                ).exists()
        else:
            field = {"created_at": "data_ins", "modified_at": "data_mod", "completed": "quantity"}.get(condition.field, condition.field)
            column = getattr(Item, field)
            if condition.field == "completed":
                column = func.coalesce(Item.quantity, 0) > 0
            predicate = comparison(
                column, condition, ITEM_FIELDS[condition.field][1], ZoneInfo(zone), current,
                timestamp=condition.field in {"created_at", "modified_at"},
            )
        predicates.append(and_(Item.inventory_id.in_(eligible), predicate))
    reducer = and_ if payload.match_mode == "all" else or_
    rows = db.execute(select(Item.id, Item.inventory_id).where(
        Item.inventory_id.in_(by_id), reducer(*predicates),
    ).order_by(Item.inventory_id, Item.id)).all()
    groups = {}
    for item_id, inventory_id in rows:
        groups.setdefault(inventory_id, []).append(item_id)
    return {
        "containers": [{
            "id": inv_id, "name": by_id[inv_id].name, "type": by_id[inv_id].type,
            "item_ids": item_ids, "count": len(item_ids),
        } for inv_id, item_ids in groups.items()],
        "total_count": len(rows),
    }


def audit_fields(row) -> dict:
    return {
        "user_ins": row.user_ins, "user_mod": row.user_mod,
        "username_ins": row.user_ins_rel.username if row.user_ins_rel else None,
        "username_mod": row.user_mod_rel.username if row.user_mod_rel else None,
        "data_ins": row.data_ins, "data_mod": row.data_mod,
    }


def filter_response(db: Session, user: User, template: FilterTemplate) -> dict:
    validation_error = None
    try:
        payload = filter_input(db, template)
        definitions = validate_filter(db, user, payload)
        scope = scope_preview(payload, visible_inventories(db, user), definitions)
        values = payload.model_dump(mode="json")
    except (HTTPException, ValueError, KeyError, TypeError) as exc:
        # Invalid legacy records stay discoverable and deletable without silently changing them.
        values = dict(name=template.name, description=template.description, is_shared=template.is_shared,
                      container_type=None, match_mode="all", conditions=[])
        scope = {"scope_type": "none", "summary": "Criteri non più compatibili", "inventories": []}
        validation_error = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else "Criteri del filtro non validi"
    count = db.query(ScheduledTrigger).filter(ScheduledTrigger.filter_id == template.id).count()
    return {
        **values, "id": template.id, **audit_fields(template), "scope_preview": scope, "trigger_count": count, "can_manage": can_manage_filter(user, template),
        "validation_error": validation_error,
    }
