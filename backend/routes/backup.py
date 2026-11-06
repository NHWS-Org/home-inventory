from __future__ import annotations

import logging
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Integer, func, inspect, select, text
from sqlalchemy.orm import Session

from backup_archive import (
    BACKUP_FORMAT,
    BACKUP_FORMAT_VERSION,
    create_backup_archive,
    decode_value,
    read_backup_archive,
    read_backup_metadata,
    read_database_snapshot,
)
from backup_comparison import compare_snapshots
from crud import get_setting, set_setting
from database import DATABASE_TYPE, SessionLocal
from dependencies import get_db, role_required
from models import Base, RoleEnum
from legacy_backup import convert_legacy_backup

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(role_required(RoleEnum.admin))])

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./data/backups"))
BACKUP_EXTENSION = ".hibackup"

DB_COMPATIBILITY_MATRIX: dict[tuple[str, str], dict[str, str]] = {
    ("4ef54a6a9ff5", "d4e5f6a7b8c9"): {
        "strategy": "forward_core_data",
        "reason": "Backup precedente all'introduzione audit/metadati: ripristino dati core consentito.",
    },
    ("b1c2d3e4f5a6", "d4e5f6a7b8c9"): {
        "strategy": "forward_core_data",
        "reason": "Backup con audit ma senza metadati: ripristino dati core consentito.",
    },
    ("c3d4e5f6a7b8", "d4e5f6a7b8c9"): {
        "strategy": "forward_core_data",
        "reason": "Backup pre-metadata: metadati facoltativi, restore consentito su schema piu recente.",
    },
}

CORE_RESTORE_TABLES = {
    "shared_inventories",
    "shared_inventory_groups",
    "item_versions",
    "inventory_versions",
    "item_metadata_values",
    "metadata_definition_assignments",
    "metadata_definitions",
    "filter_templates",
    "items",
    "item_barcodes",
    "barcode_product_cache",
    "list_assignments",
    "inventories",
    "user_group_association",
    "groups",
}

RESTORE_DELETE_ORDER = [
    "shared_inventories",
    "shared_inventory_groups",
    "list_assignments",
    "item_barcodes",
    "item_metadata_values",
    "metadata_definition_assignments",
    "filter_templates",
    "item_versions",
    "inventory_versions",
    "user_group_association",
    "items",
    "metadata_definitions",
    "barcode_product_cache",
    "groups",
    "inventories",
]

RESTORE_INSERT_ORDER = [
    "roles",
    "users",
    "groups",
    "inventories",
    "items",
    "metadata_definitions",
    "metadata_definition_assignments",
    "item_metadata_values",
    "item_barcodes",
    "barcode_product_cache",
    "list_assignments",
    "shared_inventories",
    "shared_inventory_groups",
    "user_group_association",
    "item_versions",
    "inventory_versions",
    "filter_templates",
    "settings",
]


class RestoreRequest(BaseModel):
    confirm: bool
    mode: Literal["base", "advanced"] = "base"
    overwrite_users_roles: bool = False
    overwrite_settings: bool = False
    overwrite_admin: bool = False


class BackupBulkDeleteRequest(BaseModel):
    confirm: bool
    filenames: list[str]


class BackupComparisonRequest(BaseModel):
    before_filename: str
    after_filename: str | None = None
    table: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


def _safe_backup_path(filename: str, *, extension: str = BACKUP_EXTENSION) -> Path:
    if (
        not filename
        or filename.startswith(".")
        or "/" in filename
        or "\\" in filename
        or ".." in filename
    ):
        raise HTTPException(status_code=400, detail="Nome file backup non valido")
    if not filename.endswith(extension):
        raise HTTPException(
            status_code=400,
            detail=f"Formato file non valido. Sono ammessi solo {extension}",
        )

    backup_dir_resolved = BACKUP_DIR.resolve()
    file_path = (BACKUP_DIR / filename).resolve()
    try:
        file_path.relative_to(backup_dir_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Percorso file non valido") from exc
    return file_path


def _get_alembic_version(db: Session) -> str | None:
    row = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
    return row[0] if row else None


@lru_cache(maxsize=1)
def _migration_parent_map() -> dict[str, str | None]:
    versions_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    parent_map: dict[str, str | None] = {}
    revision_re = re.compile(
        r"^revision(?:\s*:\s*[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )
    down_re = re.compile(
        r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(.+)$",
        re.MULTILINE,
    )

    for file in versions_dir.glob("*.py"):
        raw = file.read_text(encoding="utf-8")
        revision_match = revision_re.search(raw)
        down_match = down_re.search(raw)
        if not revision_match:
            continue
        revision = revision_match.group(1)
        down_revision = None
        if down_match:
            down_raw = down_match.group(1).strip()
            if down_raw != "None":
                quoted_list = re.findall(r"['\"]([^'\"]+)['\"]", down_raw)
                if quoted_list:
                    down_revision = quoted_list[0]
        parent_map[revision] = down_revision
    return parent_map


def _is_ancestor_revision(ancestor: str, descendant: str) -> bool:
    parent_map = _migration_parent_map()
    current: str | None = descendant
    while current:
        if current == ancestor:
            return True
        current = parent_map.get(current)
    return False


@lru_cache(maxsize=1)
def _migration_description_map() -> dict[str, str]:
    versions_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    descriptions: dict[str, str] = {}
    revision_re = re.compile(
        r"^revision(?:\s*:\s*[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )
    docstring_re = re.compile(r'"""(.*?)"""', re.DOTALL)

    for file in versions_dir.glob("*.py"):
        raw = file.read_text(encoding="utf-8")
        revision_match = revision_re.search(raw)
        if not revision_match:
            continue
        revision = revision_match.group(1)
        doc_match = docstring_re.search(raw)
        description = None
        if doc_match:
            description = next(
                (line.strip() for line in doc_match.group(1).splitlines() if line.strip()),
                None,
            )
        descriptions[revision] = description or file.stem.split("_", 1)[-1].replace("_", " ")
    return descriptions


def _revision_display_label(revision: str | None) -> str | None:
    if not revision:
        return None
    description = _migration_description_map().get(revision)
    return f"{description} ({revision})" if description else revision


def _list_all_revisions_in_repo() -> list[str]:
    parent_map = _migration_parent_map()
    children_map: dict[str, list[str]] = {}
    for revision, parent in parent_map.items():
        if parent is not None:
            children_map.setdefault(parent, []).append(revision)

    ordered: list[str] = []
    visited: set[str] = set()

    def walk(node: str) -> None:
        if node in visited:
            return
        visited.add(node)
        ordered.append(node)
        for child in sorted(children_map.get(node, [])):
            walk(child)

    for root in sorted(revision for revision, parent in parent_map.items() if parent is None):
        walk(root)
    ordered.extend(sorted(set(parent_map) - visited))
    return ordered


def _evaluate_restore_compatibility(
    backup_revision: str | None, current_revision: str | None
) -> dict[str, Any]:
    if not backup_revision or not current_revision:
        return {
            "compatible": False,
            "strategy": "blocked",
            "reason": "Versione alembic non disponibile",
        }
    if backup_revision == current_revision:
        return {
            "compatible": True,
            "strategy": "same_revision",
            "reason": "Revisioni identiche",
        }
    explicit_rule = DB_COMPATIBILITY_MATRIX.get((backup_revision, current_revision))
    if explicit_rule:
        return {
            "compatible": True,
            "strategy": explicit_rule["strategy"],
            "reason": explicit_rule["reason"],
        }
    if _is_ancestor_revision(backup_revision, current_revision):
        return {
            "compatible": True,
            "strategy": "forward_ancestor",
            "reason": "Backup proveniente da revisione precedente nella stessa catena migrazioni",
        }
    return {
        "compatible": False,
        "strategy": "blocked",
        "reason": "Nessuna regola compatibile nella matrice/version chain",
    }


def _table_exists(db: Session, table_name: str) -> bool:
    return inspect(db.connection()).has_table(table_name)


def _safe_delete_table(db: Session, table_name: str) -> None:
    table = Base.metadata.tables.get(table_name)
    if table is not None and _table_exists(db, table_name):
        db.execute(table.delete())


def _nullify_foreign_keys_to_users(db: Session) -> None:
    for table in Base.metadata.tables.values():
        if table.name == "users" or not _table_exists(db, table.name):
            continue
        for foreign_key in table.foreign_keys:
            column = foreign_key.parent
            if foreign_key.column.table.name == "users" and column.nullable:
                db.execute(
                    table.update()
                    .where(column.is_not(None))
                    .values({column.name: None})
                )
    user_table = Base.metadata.tables.get("users")
    if user_table is not None:
        for foreign_key in user_table.foreign_keys:
            column = foreign_key.parent
            if foreign_key.column.table.name == "users" and column.nullable:
                db.execute(
                    user_table.update()
                    .where(column.is_not(None))
                    .values({column.name: None})
                )


def _sync_id_sequences(db: Session) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return

    for table in Base.metadata.tables.values():
        if not _table_exists(db, table.name):
            continue
        for column in table.primary_key.columns:
            if not isinstance(column.type, Integer):
                continue
            sequence_name = db.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column.name},
            ).scalar_one_or_none()
            if sequence_name is None:
                continue
            max_id = db.execute(select(func.max(column))).scalar_one()
            db.execute(
                text(
                    "SELECT setval(CAST(:sequence_name AS regclass), :value, :called)"
                ),
                {
                    "sequence_name": sequence_name,
                    "value": max_id if max_id is not None else 1,
                    "called": max_id is not None,
                },
            )


def _current_admin_id(db: Session) -> Any:
    users = Base.metadata.tables.get("users")
    if users is None or not _table_exists(db, "users"):
        return None
    return db.execute(
        select(users.c.id).where(users.c.username == "admin")
    ).scalar_one_or_none()


def _foreign_keys_to_users(table: Any) -> list[Any]:
    return [
        foreign_key.parent
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name == "users"
    ]


def _insert_restored_rows(
    db: Session,
    table: Any,
    source_rows: list[dict[str, Any]],
    source_admin_id: Any,
    target_admin_id: Any,
    skip_admin: bool,
    deferred_user_refs: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]],
) -> None:
    columns = {column.name: column for column in table.columns}
    user_fk_columns = _foreign_keys_to_users(table)
    prepared_rows: list[dict[str, Any]] = []

    for source_row in source_rows:
        if table.name == "users" and source_row.get("username") == "admin" and skip_admin:
            continue

        row = {
            name: decode_value(value, columns[name].type)
            for name, value in source_row.items()
            if name in columns
        }
        for column in user_fk_columns:
            if (
                skip_admin
                and source_admin_id is not None
                and target_admin_id is not None
                and row.get(column.name) == source_admin_id
            ):
                row[column.name] = target_admin_id

        if table.name in {"users", "roles"}:
            deferred: dict[str, Any] = {}
            for column in user_fk_columns:
                if column.name in row and column.nullable:
                    deferred[column.name] = row[column.name]
                    row[column.name] = None
            if deferred:
                deferred_user_refs.setdefault(table.name, []).append((row, deferred))
        prepared_rows.append(row)

    if prepared_rows:
        db.execute(table.insert(), prepared_rows)


def _restore_backup_rows(
    db: Session,
    rows_by_table: dict[str, list[dict[str, Any]]],
    payload: RestoreRequest,
    metadata: dict[str, Any],
) -> None:
    # Never retain runnable outbox work across a restore, including preserved admin rows.
    _safe_delete_table(db, "push_deliveries")
    _safe_delete_table(db, "push_subscriptions")
    _safe_delete_table(db, "notifications")
    _safe_delete_table(db, "notification_events")
    _safe_delete_table(db, "notification_rules")
    selected_tables = set(CORE_RESTORE_TABLES) | {"users"}
    overwrite_roles = payload.mode == "advanced" and payload.overwrite_users_roles
    if overwrite_roles:
        selected_tables.add("roles")
    if payload.mode == "advanced" and payload.overwrite_settings:
        selected_tables.add("settings")

    target_admin_id = _current_admin_id(db)
    source_admin_id = metadata.get("admin_user_id")

    for table_name in RESTORE_DELETE_ORDER:
        if table_name in selected_tables:
            _safe_delete_table(db, table_name)

    _nullify_foreign_keys_to_users(db)
    users = Base.metadata.tables["users"]
    if overwrite_roles and payload.overwrite_admin:
        db.execute(users.delete())
        _safe_delete_table(db, "roles")
    else:
        db.execute(users.delete().where(users.c.username != "admin"))

    if payload.mode == "advanced" and payload.overwrite_settings:
        _safe_delete_table(db, "settings")

    skip_admin = not (
        payload.mode == "advanced"
        and payload.overwrite_users_roles
        and payload.overwrite_admin
    )
    if (
        skip_admin
        and source_admin_id is not None
        and target_admin_id is None
        and rows_by_table.get("users")
    ):
        raise ValueError("Impossibile preservare l'utente admin: non esiste nel database")

    deferred_user_refs: dict[
        str, list[tuple[dict[str, Any], dict[str, Any]]]
    ] = {}
    for table_name in RESTORE_INSERT_ORDER:
        if table_name not in selected_tables:
            continue
        table = Base.metadata.tables.get(table_name)
        if (
            table is None
            or not _table_exists(db, table_name)
            or not rows_by_table.get(table_name)
        ):
            continue
        _insert_restored_rows(
            db,
            table,
            rows_by_table[table_name],
            source_admin_id,
            target_admin_id,
            skip_admin,
            deferred_user_refs,
        )

    for table_name, deferred_rows in deferred_user_refs.items():
        table = Base.metadata.tables[table_name]
        primary_key = list(table.primary_key.columns)
        for inserted_row, deferred in deferred_rows:
            identity = {column.name: inserted_row[column.name] for column in primary_key}
            predicate = [table.c[name] == value for name, value in identity.items()]
            db.execute(
                table.update()
                .where(*predicate)
                .values(deferred)
            )

    _sync_id_sequences(db)


@router.post("/create")
def create_backup(db: Session = Depends(get_db), prefix: str = "manual"):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", prefix):
        raise HTTPException(status_code=400, detail="Prefisso backup non valido")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_backup_{timestamp}{BACKUP_EXTENSION}"
    full_backup_path = _safe_backup_path(filename)
    metadata = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "db_type": DATABASE_TYPE,
        "db_alembic_version": _get_alembic_version(db),
    }
    if not metadata["db_alembic_version"]:
        raise HTTPException(status_code=500, detail="Versione Alembic del database non disponibile")

    try:
        create_backup_archive(db, full_backup_path, metadata)
        logger.info("Backup completato: %s", full_backup_path.name)
    except Exception as exc:
        logger.exception("Errore durante la creazione del backup %s", filename)
        if full_backup_path.exists():
            full_backup_path.unlink()
        raise HTTPException(status_code=500, detail=f"Errore nel backup: {exc}") from exc

    return {"message": "Backup creato", "filename": full_backup_path.name}


@router.get("/")
def list_backups(db: Session = Depends(get_db)):
    current_revision = _get_alembic_version(db)
    backups = []
    for file in sorted(BACKUP_DIR.glob(f"*{BACKUP_EXTENSION}")):
        metadata_error = None
        try:
            metadata = read_backup_metadata(file)
        except ValueError as exc:
            metadata = None
            metadata_error = str(exc)
        backup_revision = metadata.get("db_alembic_version") if metadata else None
        compatibility = _evaluate_restore_compatibility(backup_revision, current_revision)
        backups.append(
            {
                "filename": file.name,
                "size": file.stat().st_size,
                "modified": datetime.fromtimestamp(file.stat().st_mtime),
                "metadata": metadata,
                "metadata_error": metadata_error,
                "has_metadata": metadata is not None,
                "db_alembic_version": backup_revision,
                "db_alembic_version_label": _revision_display_label(backup_revision),
                "current_db_alembic_version": current_revision,
                "current_db_alembic_version_label": _revision_display_label(current_revision),
                "restorable_on_current_db": bool(
                    metadata and compatibility.get("compatible")
                ),
                "restore_compatibility": compatibility,
            }
        )
    for file in sorted(BACKUP_DIR.glob("*.sql")):
        try:
            sql_path = _safe_backup_path(file.name, extension=".sql")
            metadata_path = _safe_backup_path(f"{file.name}.meta.json", extension=".sql.meta.json")
        except HTTPException:
            logger.warning("Backup legacy con percorso non valido ignorato")
            continue
        if not sql_path.is_file():
            continue
        has_metadata = metadata_path.is_file()
        backups.append({
            "filename": file.name,
            "size": sql_path.stat().st_size + (metadata_path.stat().st_size if has_metadata else 0),
            "modified": datetime.fromtimestamp(sql_path.stat().st_mtime),
            "legacy": True,
            "has_metadata": has_metadata,
            "restorable_on_current_db": False,
        })
    return backups


@router.post("/convert-legacy/{filename}")
def convert_legacy_backup_in_place(filename: str):
    sql_path = _safe_backup_path(filename, extension=".sql")
    metadata_path = _safe_backup_path(f"{filename}.meta.json", extension=".sql.meta.json")
    output = _safe_backup_path(f"{filename[:-4]}{BACKUP_EXTENSION}")
    if not sql_path.is_file() or not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="Servono entrambi i file .sql e .sql.meta.json")
    if output.exists():
        raise HTTPException(status_code=409, detail="Il backup .hibackup di destinazione esiste gia")
    staging = BACKUP_DIR / f".conversion-{uuid.uuid4().hex}.tmp"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        convert_legacy_backup(sql_path.read_text(encoding="utf-8-sig"), metadata, staging)
        read_backup_metadata(staging)
        # Publish without overwriting an existing archive, even during concurrent conversions.
        os.link(staging, output)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="Il backup .hibackup di destinazione esiste gia") from exc
    except (ValueError, TypeError, ArithmeticError, RecursionError) as exc:
        logger.warning("Conversione backup legacy rifiutata: dati non validi")
        raise HTTPException(status_code=400, detail="Backup legacy o metadati non validi") from exc
    except OSError as exc:
        logger.exception("Errore nella conversione del backup legacy")
        raise HTTPException(status_code=500, detail="Impossibile convertire il backup legacy") from exc
    finally:
        staging.unlink(missing_ok=True)
    return {"message": "Backup convertito; sorgenti conservati", "filename": output.name}


@router.delete("/legacy/{filename}")
def delete_legacy_backup(filename: str, confirm: bool = Body(...)):
    if not confirm:
        raise HTTPException(status_code=400, detail="Cancellazione non confermata")
    sql_path = _safe_backup_path(filename, extension=".sql")
    metadata_path = _safe_backup_path(f"{filename}.meta.json", extension=".sql.meta.json")
    if not sql_path.is_file() and not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="File sorgenti non trovati")
    try:
        metadata_path.unlink(missing_ok=True)
        sql_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.exception("Errore durante la cancellazione dei sorgenti legacy")
        raise HTTPException(
            status_code=500,
            detail="Cancellazione dei sorgenti incompleta: verificare i file rimasti",
        ) from exc
    return {"message": "File sorgenti legacy eliminati"}


@router.get("/compatibility-map")
def get_backup_compatibility_map():
    revisions = _list_all_revisions_in_repo()
    revision_labels = {
        revision: _revision_display_label(revision) for revision in revisions
    }
    matrix = []
    for source in revisions:
        targets = []
        for target in revisions:
            compatibility = _evaluate_restore_compatibility(source, target)
            targets.append(
                {
                    "target_revision": target,
                    "compatible": compatibility.get("compatible", False),
                    "strategy": compatibility.get("strategy"),
                    "reason": compatibility.get("reason"),
                }
            )
        matrix.append({"source_revision": source, "targets": targets})

    return {
        "revisions": revisions,
        "revision_labels": revision_labels,
        "matrix": matrix,
        "explicit_rules": [
            {
                "source_revision": source,
                "target_revision": target,
                "strategy": rule.get("strategy"),
                "reason": rule.get("reason"),
            }
            for (source, target), rule in sorted(DB_COMPATIBILITY_MATRIX.items())
        ],
    }


@router.post("/compare")
def compare_backups(payload: BackupComparisonRequest, db: Session = Depends(get_db)):
    def load(filename: str) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
        path = _safe_backup_path(filename)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="File backup non trovato")
        metadata, rows = read_backup_archive(path)
        table_names = metadata.get("tables", [])
        if not isinstance(table_names, list) or not all(
            isinstance(name, str) for name in table_names
        ):
            raise ValueError("Elenco tabelle del backup non valido")
        for table_name in table_names:
            rows.setdefault(table_name, [])
        return metadata, rows

    try:
        before_meta, before = load(payload.before_filename)
        if payload.after_filename is not None:
            after_meta, after = load(payload.after_filename)
        else:
            after_meta = {"db_alembic_version": _get_alembic_version(db)}
            after = read_database_snapshot(db)
        result = compare_snapshots(
            before, after, table_filter=payload.table,
            offset=payload.offset, limit=payload.limit,
        )
    except (ValueError, TypeError, RecursionError) as exc:
        logger.warning("Confronto backup rifiutato: dati non validi")
        raise HTTPException(
            status_code=400,
            detail="Impossibile confrontare i backup: archivio, tabella o dati non validi",
        ) from exc
    return {
        **result,
        "before": {
            "filename": payload.before_filename,
            "db_alembic_version": before_meta.get("db_alembic_version"),
        },
        "after": {
            "filename": payload.after_filename,
            "db_alembic_version": after_meta.get("db_alembic_version"),
        },
    }


@router.get("/download/{filename}")
def download_backup(filename: str):
    file_path = _safe_backup_path(filename)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File non trovato")
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/octet-stream",
    )


@router.delete("/delete/{filename}")
def delete_backup(filename: str, confirm: bool = Body(...)):
    if not confirm:
        raise HTTPException(status_code=400, detail="Cancellazione non confermata")
    file_path = _safe_backup_path(filename)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File non trovato")
    file_path.unlink()
    return {"message": "Backup cancellato"}


@router.post("/delete-bulk")
def delete_backups_bulk(payload: BackupBulkDeleteRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Cancellazione non confermata")
    if not payload.filenames:
        raise HTTPException(status_code=400, detail="Nessun backup selezionato")

    deleted: list[str] = []
    missing: list[str] = []
    invalid: list[str] = []
    for filename in payload.filenames:
        try:
            file_path = _safe_backup_path(filename)
        except HTTPException:
            invalid.append(filename)
            continue
        if not file_path.is_file():
            missing.append(filename)
            continue
        try:
            file_path.unlink()
            deleted.append(filename)
        except OSError:
            logger.exception("Errore durante la cancellazione del backup %s", filename)
            missing.append(filename)
    return {
        "message": "Cancellazione massiva completata",
        "deleted": deleted,
        "missing": missing,
        "invalid": invalid,
    }


@router.post("/restore/{filename}")
def restore_backup(filename: str, payload: RestoreRequest = Body(...)):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Restore non confermato")
    file_path = _safe_backup_path(filename)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File non trovato")
    if payload.mode == "advanced" and payload.overwrite_users_roles and not payload.overwrite_admin:
        raise HTTPException(
            status_code=400,
            detail="Per sovrascrivere utenti/ruoli è necessario abilitare anche overwrite_admin",
        )

    try:
        metadata, rows_by_table = read_backup_archive(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    compatibility_db = SessionLocal()
    try:
        current_revision = _get_alembic_version(compatibility_db)
    finally:
        compatibility_db.close()
    compatibility = _evaluate_restore_compatibility(
        metadata.get("db_alembic_version"), current_revision
    )
    if not compatibility.get("compatible"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Backup non ripristinabile su questo DB: "
                f"versione backup={metadata.get('db_alembic_version')} "
                f"versione corrente={current_revision}. "
                f"Motivo: {compatibility.get('reason')}"
            ),
        )

    db = SessionLocal()
    try:
        with db.begin():
            _restore_backup_rows(db, rows_by_table, payload, metadata)
        logger.info("Restore completato per il file: %s", filename)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Errore durante il restore del file %s", filename)
        raise HTTPException(status_code=500, detail=f"Errore durante il restore: {exc}") from exc
    finally:
        db.close()

    return {
        "message": "Restore completato",
        "mode": payload.mode,
        "compatibility": compatibility,
    }


@router.post("/upload")
def upload_backup(
    file: UploadFile = File(...),
    metadata_file: UploadFile | None = File(None),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome file non fornito")
    original_name = file.filename.replace("\\", "/").rsplit("/", 1)[-1]
    legacy = original_name.endswith(".sql")
    if not original_name.endswith(BACKUP_EXTENSION) and not legacy:
        raise HTTPException(
            status_code=400,
            detail=f"Sono ammessi {BACKUP_EXTENSION} oppure .sql con .sql.meta.json",
        )
    if legacy and (
        metadata_file is None
        or metadata_file.filename is None
        or metadata_file.filename.replace("\\", "/").rsplit("/", 1)[-1]
        != f"{original_name}.meta.json"
    ):
        raise HTTPException(
            status_code=400,
            detail="Seleziona il file .sql.meta.json corrispondente al backup SQL",
        )
    if not legacy and metadata_file is not None:
        raise HTTPException(status_code=400, detail="Un backup .hibackup non richiede metadati separati")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"uploaded_{timestamp}_{uuid.uuid4().hex}{BACKUP_EXTENSION}"
    file_path = _safe_backup_path(filename)

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        if legacy and metadata_file is not None:
            metadata = json.load(metadata_file.file)
            sql = file.file.read().decode("utf-8-sig")
            convert_legacy_backup(sql, metadata, file_path)
        else:
            with file_path.open("wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        read_backup_metadata(file_path)
    except (OSError, ValueError) as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Backup non valido: {exc}") from exc
    finally:
        file.file.close()
        if metadata_file is not None:
            metadata_file.file.close()

    logger.info("File di backup caricato: %s", file_path.name)
    return {
        "message": "Backup convertito e caricato" if legacy else "Backup caricato correttamente",
        "filename": file_path.name,
        "converted": legacy,
    }


@router.get("/schedule")
def get_backup_schedule(db: Session = Depends(get_db)):
    frequency = get_setting(db, "BACKUP_FREQUENCY")
    int_days = get_setting(db, "BACKUP_INTERVAL_DAYS")
    int_hours = get_setting(db, "BACKUP_INTERVAL_HOURS")
    int_minutes = get_setting(db, "BACKUP_INTERVAL_MINUTES")
    retention = get_setting(db, "BACKUP_RETENTION")
    return {
        "BACKUP_FREQUENCY": frequency,
        "BACKUP_INTERVAL_DAYS": int_days,
        "BACKUP_INTERVAL_HOURS": int_hours,
        "BACKUP_INTERVAL_MINUTES": int_minutes,
        "BACKUP_RETENTION": retention,
    }


@router.post("/schedule")
def set_backup_schedule(
    backup_frequency: str = Body(..., embed=True),
    backup_int_days: int = Body(..., embed=True),
    backup_int_hours: int = Body(..., embed=True),
    backup_int_minutes: int = Body(..., embed=True),
    backup_retention: int = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    set_setting(db, "BACKUP_FREQUENCY", str(backup_frequency))
    set_setting(db, "BACKUP_INTERVAL_DAYS", str(backup_int_days))
    set_setting(db, "BACKUP_INTERVAL_HOURS", str(backup_int_hours))
    set_setting(db, "BACKUP_INTERVAL_MINUTES", str(backup_int_minutes))
    set_setting(db, "BACKUP_RETENTION", str(backup_retention))

    try:
        from scheduler import start_scheduler

        start_scheduler()
    except Exception as exc:
        logger.exception("Errore durante l'avvio dello scheduler")
        raise HTTPException(
            status_code=500,
            detail=f"Errore durante l'avvio dello scheduler: {exc}",
        ) from exc
    return {"message": "Schedulazione aggiornata correttamente"}


@router.post("/schedule/trigger")
def trigger_backup_now(db: Session = Depends(get_db)):
    try:
        from scheduler import scheduled_backup

        scheduled_backup()
        return {"message": "Backup schedulato avviato"}
    except Exception as exc:
        logger.exception("Errore durante il trigger manuale del backup")
        raise HTTPException(
            status_code=500,
            detail=f"Errore durante il trigger manuale del backup: {exc}",
        ) from exc
