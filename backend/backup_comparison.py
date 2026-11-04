from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from backup_archive import decode_value
from models import Base


REDACTED = "[oscurato]"
SENSITIVE_FIELD = re.compile(
    r"password|passwd|secret|token|api[_-]?key|credential|private[_-]?key|hash",
    re.IGNORECASE,
)


def _normalize_row(table_name: str, row: dict[str, Any]) -> dict[str, Any]:
    table = Base.metadata.tables[table_name]
    normalized = {}
    for field, value in row.items():
        if field in table.c:
            try:
                value = decode_value(value, table.c[field].type)
            except (TypeError, ValueError, ArithmeticError) as exc:
                raise ValueError("Valore tipizzato non valido nel backup") from exc
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("Valore numerico non finito nel backup")
        if isinstance(value, datetime) and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        normalized[field] = value
    return normalized


def _public_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            key: REDACTED if SENSITIVE_FIELD.search(key) else _public_value(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_public_value(child) for child in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            return value
        if isinstance(parsed, (dict, list)):
            return _public_value(parsed)
    return value


def _field_value(table: str, field: str, value: Any) -> Any:
    # Settings can contain arbitrary credentials under names not known to the app.
    if SENSITIVE_FIELD.search(field) or (table == "settings" and field == "value"):
        return REDACTED
    return _public_value(value)


def _index_rows(
    table_name: str, rows: list[dict[str, Any]]
) -> dict[tuple[Any, ...], dict[str, Any]]:
    table = Base.metadata.tables.get(table_name)
    if table is None:
        raise ValueError(f"Tabella non supportata per il confronto: {table_name}")
    primary_key = [column.name for column in table.primary_key.columns]
    indexed = {}
    for row in rows:
        if any(field not in row or row[field] is None for field in primary_key):
            raise ValueError(f"Chiave primaria mancante nella tabella {table_name}")
        normalized = _normalize_row(table_name, row)
        for field in primary_key:
            expected_type = table.c[field].type.python_type
            value = normalized[field]
            if not isinstance(value, expected_type) or (
                expected_type is int and isinstance(value, bool)
            ):
                raise ValueError(f"Tipo della chiave primaria non valido in {table_name}")
        key = tuple(normalized[field] for field in primary_key)
        try:
            if key in indexed:
                raise ValueError(f"Chiave primaria duplicata nella tabella {table_name}")
            indexed[key] = normalized
        except TypeError as exc:
            raise ValueError(f"Chiave primaria non valida nella tabella {table_name}") from exc
    return indexed


def compare_snapshots(
    before: dict[str, list[dict[str, Any]]],
    after: dict[str, list[dict[str, Any]]],
    *,
    table_filter: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    table_names = sorted(before.keys() | after.keys())
    if table_filter is not None and table_filter not in table_names:
        raise ValueError("Tabella non presente nel confronto")
    summaries = []
    changes = []
    total_changes = 0
    for table_name in table_names:
        left = _index_rows(table_name, before.get(table_name, []))
        right = _index_rows(table_name, after.get(table_name, []))
        summary = {
            "table": table_name,
            "before_count": len(left),
            "after_count": len(right),
            "before_present": table_name in before,
            "after_present": table_name in after,
            "added": 0,
            "removed": 0,
            "modified": 0,
            "unchanged": 0,
        }
        for key in sorted(left.keys() | right.keys(), key=repr):
            old = left.get(key, {})
            new = right.get(key, {})
            kind = "added" if key not in left else "removed" if key not in right else "modified"
            fields = [
                field for field in sorted(old.keys() | new.keys())
                if field not in old or field not in new or old[field] != new[field]
            ]
            if not fields:
                summary["unchanged"] += 1
                continue
            summary[kind] += 1
            if table_filter is not None and table_name != table_filter:
                continue
            if offset <= total_changes < offset + limit:
                primary_key = Base.metadata.tables[table_name].primary_key.columns
                changes.append({
                    "table": table_name,
                    "key": {
                        column.name: _field_value(table_name, column.name, value)
                        for column, value in zip(primary_key, key)
                    },
                    "kind": kind,
                    "fields": [{
                        "field": field,
                        "before_present": field in old,
                        "after_present": field in new,
                        "before": _field_value(table_name, field, old.get(field)),
                        "after": _field_value(table_name, field, new.get(field)),
                    } for field in fields],
                })
            total_changes += 1
        summaries.append(summary)
    return {
        "tables": summaries,
        "changes": changes,
        "total_changes": total_changes,
        "offset": offset,
        "limit": limit,
    }
