from __future__ import annotations

import base64
import json
import os
import tempfile
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from collections.abc import Iterable

from sqlalchemy import JSON, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.sqltypes import Date, DateTime, LargeBinary, Numeric, Time

from models import Base

BACKUP_FORMAT = "home-inventory-backup-v3"
BACKUP_FORMAT_VERSION = 1


def encode_value(value: Any, column_type: Any) -> Any:
    if value is None:
        return None
    if isinstance(column_type, DateTime):
        return {"$hib_type": "datetime", "value": value.isoformat()}
    if isinstance(column_type, Date):
        return {"$hib_type": "date", "value": value.isoformat()}
    if isinstance(column_type, Time):
        return {"$hib_type": "time", "value": value.isoformat()}
    if isinstance(column_type, Numeric):
        return {"$hib_type": "decimal", "value": str(value)}
    if isinstance(column_type, LargeBinary):
        return {"$hib_type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    return value


def decode_value(value: Any, column_type: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict) or "$hib_type" not in value:
        return value
    if isinstance(column_type, JSON):
        return value

    kind = value["$hib_type"]
    raw = value.get("value")
    if kind == "datetime" and isinstance(column_type, DateTime):
        return datetime.fromisoformat(raw)
    if kind == "date" and isinstance(column_type, Date):
        return date.fromisoformat(raw)
    if kind == "time" and isinstance(column_type, Time):
        return time.fromisoformat(raw)
    if kind == "decimal" and isinstance(column_type, Numeric):
        return Decimal(raw)
    if kind == "bytes" and isinstance(column_type, LargeBinary):
        return base64.b64decode(raw, validate=True)
    raise ValueError(f"Valore tipizzato non valido per la colonna ({kind})")


def read_backup_metadata(
    file_path: Path,
    *,
    require_alembic_revision: bool = True,
) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(file_path, "r") as archive:
            names = set(archive.namelist())
            if not {"manifest.json", "data.jsonl"}.issubset(names):
                raise ValueError("Archivio backup incompleto")
            metadata = json.loads(archive.read("manifest.json"))
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError(f"Archivio backup non valido: {exc}") from exc

    if (
        not isinstance(metadata, dict)
        or metadata.get("format") != BACKUP_FORMAT
        or metadata.get("format_version") != BACKUP_FORMAT_VERSION
        or (require_alembic_revision and not metadata.get("db_alembic_version"))
    ):
        raise ValueError("Formato o metadati del backup non supportati")
    return metadata


def read_backup_archive(
    file_path: Path,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    metadata = read_backup_metadata(file_path)
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    try:
        with zipfile.ZipFile(file_path, "r") as archive:
            with archive.open("data.jsonl") as data_file:
                for line_number, raw_line in enumerate(data_file, start=1):
                    if not raw_line.strip():
                        continue
                    try:
                        record = json.loads(raw_line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"Record backup non valido alla riga {line_number}"
                        ) from exc
                    if (
                        not isinstance(record, dict)
                        or not isinstance(record.get("table"), str)
                        or not isinstance(record.get("row"), dict)
                    ):
                        raise ValueError(
                            f"Record backup non valido alla riga {line_number}"
                        )
                    rows_by_table.setdefault(record["table"], []).append(record["row"])
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise ValueError(f"Impossibile leggere i dati del backup: {exc}") from exc
    return metadata, rows_by_table


def create_backup_archive(
    db: Session,
    file_path: Path,
    metadata: dict[str, Any],
) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    connection = db.connection()
    inspector = inspect(connection)
    tables: list[tuple[Any, list[Any]]] = []
    for table in Base.metadata.tables.values():
        if not inspector.has_table(table.name):
            continue
        available_columns = {
            column["name"] for column in inspector.get_columns(table.name)
        }
        columns = [column for column in table.columns if column.name in available_columns]
        if columns:
            tables.append((table, columns))

    metadata["tables"] = [table.name for table, _columns in tables]
    users = Base.metadata.tables.get("users")
    if users is not None and "users" in metadata["tables"]:
        user_columns = {column.name for column in next(
            columns for table, columns in tables if table.name == "users"
        )}
        if {"id", "username"}.issubset(user_columns):
            metadata["admin_user_id"] = db.execute(
                select(users.c.id).where(users.c.username == "admin")
            ).scalar_one_or_none()

    def records():
        for table, columns in tables:
            result = db.execute(select(*columns))
            while rows := result.mappings().fetchmany(500):
                for row in rows:
                    yield {
                        "table": table.name,
                        "row": {
                            column.name: encode_value(row[column.name], column.type)
                            for column in columns
                        },
                    }

    write_backup_archive(file_path, metadata, records())


def write_backup_archive(
    file_path: Path,
    metadata: dict[str, Any],
    records: Iterable[dict[str, Any]],
) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_handle = tempfile.NamedTemporaryFile(
        dir=file_path.parent,
        prefix=".backup-",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()
    try:
        with zipfile.ZipFile(
            temp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(metadata, ensure_ascii=True, separators=(",", ":")),
            )
            data_info = zipfile.ZipInfo("data.jsonl")
            data_info.compress_type = zipfile.ZIP_DEFLATED
            with archive.open(data_info, mode="w") as data_file:
                for record in records:
                    data_file.write(
                        (json.dumps(record, ensure_ascii=True) + "\n").encode("utf-8")
                    )
        os.replace(temp_path, file_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
