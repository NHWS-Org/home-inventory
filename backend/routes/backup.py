from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import FileResponse
from fastapi import UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from pathlib import Path
import os
import subprocess
import threading
import logging
import json
import re
import uuid
from functools import lru_cache
from dependencies import get_db, role_required
from models import RoleEnum
from dotenv import load_dotenv
from database import SessionLocal
from crud import get_setting, set_setting
from pydantic import BaseModel
from typing import Literal

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(role_required(RoleEnum.admin))])

BACKUP_DIR = Path("./backups")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

BACKUP_META_PREFIX = "-- HI_BACKUP_META: "

# Matrice di compatibilita DB (source_revision -> target_revision)
# Va mantenuta nel tempo per esplicitare restore cross-version consentiti.
DB_COMPATIBILITY_MATRIX: dict[tuple[str, str], dict] = {
    (
        "4ef54a6a9ff5",
        "d4e5f6a7b8c9",
    ): {
        "strategy": "forward_core_data",
        "reason": "Backup precedente all'introduzione audit/metadati: ripristino dati core consentito.",
    },
    (
        "b1c2d3e4f5a6",
        "d4e5f6a7b8c9",
    ): {
        "strategy": "forward_core_data",
        "reason": "Backup con audit ma senza metadati: ripristino dati core consentito.",
    },
    (
        "c3d4e5f6a7b8",
        "d4e5f6a7b8c9",
    ): {
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
    "list_assignments",
    "inventories",
    "user_group_association",
    "groups",
}


class RestoreRequest(BaseModel):
    confirm: bool
    mode: Literal["base", "advanced"] = "base"
    overwrite_users_roles: bool = False
    overwrite_settings: bool = False
    overwrite_admin: bool = False


class BackupBulkDeleteRequest(BaseModel):
    confirm: bool
    filenames: list[str]


def _safe_backup_path(filename: str) -> Path:
    """Valida e sanitizza il nome file di backup per prevenire vulnerabilità di Path Traversal."""
    if not filename or filename.startswith(".") or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome file non valido: tentato path traversal")
    if not filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail="Formato file non valido. Solo file .sql ammessi")

    backup_dir_resolved = BACKUP_DIR.resolve()
    file_path = (BACKUP_DIR / filename).resolve()

    try:
        file_path.relative_to(backup_dir_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="Percorso file non valido")

    return file_path


def _backup_meta_path(file_path: Path) -> Path:
    return file_path.parent / f"{file_path.name}.meta.json"


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
    current = descendant
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

        description = None
        doc_match = docstring_re.search(raw)
        if doc_match:
            for line in doc_match.group(1).splitlines():
                clean = line.strip()
                if clean:
                    description = clean
                    break

        if not description:
            stem = file.stem
            description = stem.split("_", 1)[1].replace("_", " ") if "_" in stem else stem

        descriptions[revision] = description

    return descriptions


def _revision_display_label(revision: str | None) -> str | None:
    if not revision:
        return None
    description = _migration_description_map().get(revision)
    if not description:
        return revision
    return f"{description} ({revision})"


def _list_all_revisions_in_repo() -> list[str]:
    parent_map = _migration_parent_map()
    if not parent_map:
        return []

    children_map: dict[str, list[str]] = {}
    for revision, parent in parent_map.items():
        if parent is None:
            continue
        children_map.setdefault(parent, []).append(revision)

    roots = sorted([revision for revision, parent in parent_map.items() if parent is None])
    ordered: list[str] = []
    visited: set[str] = set()

    def walk(node: str) -> None:
        if node in visited:
            return
        visited.add(node)
        ordered.append(node)
        for child in sorted(children_map.get(node, [])):
            walk(child)

    for root in roots:
        walk(root)

    # Safety: include eventual orfani non raggiunti
    for revision in sorted(parent_map.keys()):
        if revision not in visited:
            ordered.append(revision)

    return ordered


def _evaluate_restore_compatibility(backup_revision: str | None, current_revision: str | None) -> dict:
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
            "strategy": explicit_rule.get("strategy", "matrix"),
            "reason": explicit_rule.get("reason", "Compatibilita esplicita in matrice"),
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
    row = db.execute(text("SELECT to_regclass(:table_name)"), {"table_name": table_name}).fetchone()
    return bool(row and row[0])


def _safe_delete_table(db: Session, table_name: str) -> None:
    if _table_exists(db, table_name):
        db.execute(text(f"DELETE FROM {table_name}"))


def _sync_id_sequences(db: Session) -> None:
    """Riallinea le sequence PostgreSQL delle colonne `id` al valore max presente.

    Utile dopo restore da dump quando i setval del backup sono assenti/non aggiornati.
    """
    db.execute(
        text(
            """
            DO $$
            DECLARE
                seq_record RECORD;
                max_id BIGINT;
            BEGIN
                FOR seq_record IN
                    SELECT
                        n.nspname AS schema_name,
                        c.relname AS table_name,
                        a.attname AS column_name,
                        pg_get_serial_sequence(format('%I.%I', n.nspname, c.relname), a.attname) AS sequence_name
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_attribute a ON a.attrelid = c.oid
                    WHERE c.relkind = 'r'
                      AND n.nspname = 'public'
                      AND a.attnum > 0
                      AND NOT a.attisdropped
                      AND a.attname = 'id'
                LOOP
                    IF seq_record.sequence_name IS NOT NULL THEN
                        EXECUTE format(
                            'SELECT COALESCE(MAX(%I), 0) FROM %I.%I',
                            seq_record.column_name,
                            seq_record.schema_name,
                            seq_record.table_name
                        ) INTO max_id;

                        -- false => il prossimo nextval restituira esattamente max_id + 1
                        EXECUTE format(
                            'SELECT setval(%L, %s, false)',
                            seq_record.sequence_name,
                            max_id + 1
                        );
                    END IF;
                END LOOP;
            END
            $$;
            """
        )
    )
    db.commit()


def _nullify_foreign_keys_to_users(db: Session) -> None:
    """Imposta a NULL tutte le FK nullable che puntano a users.id.

    Serve prima della cancellazione massiva utenti nel restore avanzato,
    per evitare violazioni su colonne audit (es. roles.user_ins/user_mod).
    """
    db.execute(
        text(
            """
            DO $$
            DECLARE
                fk_record RECORD;
            BEGIN
                FOR fk_record IN
                    SELECT
                        n.nspname AS schema_name,
                        c.relname AS table_name,
                        a.attname AS column_name,
                        a.attnotnull AS is_not_null
                    FROM pg_constraint con
                    JOIN pg_class c ON c.oid = con.conrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN unnest(con.conkey) WITH ORDINALITY AS cols(attnum, ord) ON TRUE
                    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = cols.attnum
                    WHERE con.contype = 'f'
                      AND con.confrelid = 'public.users'::regclass
                LOOP
                    IF fk_record.is_not_null THEN
                        CONTINUE;
                    END IF;

                    EXECUTE format(
                        'UPDATE %I.%I SET %I = NULL WHERE %I IS NOT NULL',
                        fk_record.schema_name,
                        fk_record.table_name,
                        fk_record.column_name,
                        fk_record.column_name
                    );
                END LOOP;
            END
            $$;
            """
        )
    )
    db.commit()


def _write_backup_metadata(file_path: Path, metadata: dict) -> None:
    meta_path = _backup_meta_path(file_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=True, indent=2)


def _prepend_backup_metadata_comment(file_path: Path, metadata: dict) -> None:
    # Manteniamo i backup single-file auto-descrittivi anche in caso di upload/download solo .sql
    meta_line = f"{BACKUP_META_PREFIX}{json.dumps(metadata, ensure_ascii=True)}\n"
    with open(file_path, "r", encoding="utf-8") as f:
        original = f.read()
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(meta_line)
        f.write(original)


def _read_backup_metadata(file_path: Path) -> dict | None:
    sidecar = _backup_meta_path(file_path)
    if sidecar.exists():
        with open(sidecar, "r", encoding="utf-8") as f:
            return json.load(f)

    with open(file_path, "r", encoding="utf-8") as f:
        for _ in range(30):
            line = f.readline()
            if not line:
                break
            if line.startswith(BACKUP_META_PREFIX):
                raw = line[len(BACKUP_META_PREFIX):].strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return None
    return None


def _build_filtered_restore_sql(
    source_file: Path,
    output_file: Path,
    include_tables: set[str],
    skip_admin_insert: bool,
) -> None:
    insert_re = re.compile(r"^INSERT INTO (?:public\.)?\"?([a-zA-Z0-9_]+)\"? ")
    setval_re = re.compile(r"^SELECT pg_catalog\.setval\('(?:public\.)?\"?([a-zA-Z0-9_]+)_")

    with open(source_file, "r", encoding="utf-8") as src, open(output_file, "w", encoding="utf-8") as dst:
        for line in src:
            if line.startswith(BACKUP_META_PREFIX):
                continue

            ins = insert_re.match(line)
            if ins:
                table = ins.group(1)
                if table not in include_tables:
                    continue
                if table == "users" and skip_admin_insert and "'admin'" in line:
                    continue
                dst.write(line)
                continue

            seq = setval_re.match(line)
            if seq:
                table = seq.group(1)
                if table not in include_tables:
                    continue
                dst.write(line)
                continue

            # Manteniamo SET/SELECT/COMMENT utili al restore
            dst.write(line)

@router.post("/create")
def create_backup(db: Session = Depends(get_db), prefix: str = "manual"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_backup_{timestamp}.sql"
    full_backup_path = _safe_backup_path(filename)

    try:
        env = os.environ.copy()
        env["PGPASSWORD"] = os.getenv("POSTGRES_PASSWORD", "admin")

        logger.info(f"Avvio backup: {full_backup_path.name}")

        # Backup totale data-only: include tutte le tabelle/record
        subprocess.run([
            "pg_dump",
            "-U", os.getenv("POSTGRES_USER", "admin"),
            "-h", os.getenv("POSTGRES_HOST", "db"),
            "-d", os.getenv("POSTGRES_DB", "inventory"),
            "--data-only",
            "--disable-triggers", #Aggiunto per evitare problemi di FK durante il restore, soprattutto con tabelle condivise e versioning
            "--column-inserts",
            "-f", str(full_backup_path)
        ], check=True, env=env)

        metadata = {
            "format": "home-inventory-backup-v2",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "db_alembic_version": _get_alembic_version(db),
        }
        _write_backup_metadata(full_backup_path, metadata)
        _prepend_backup_metadata_comment(full_backup_path, metadata)

        logger.info(f"Backup completato: {full_backup_path.name}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nel backup: {str(e)}")

    return {"message": "Backup creato", "filename": full_backup_path.name}

@router.get("/")
def list_backups(db: Session = Depends(get_db)):
    backups = []
    current_revision = _get_alembic_version(db)
    for file in sorted(BACKUP_DIR.glob("*.sql")):
        metadata = _read_backup_metadata(file)
        backup_revision = metadata.get("db_alembic_version") if metadata else None
        compatibility = _evaluate_restore_compatibility(backup_revision, current_revision)
        backups.append({
            "filename": file.name,
            "size": file.stat().st_size,
            "modified": datetime.fromtimestamp(file.stat().st_mtime),
            "metadata": metadata,
            "has_metadata": metadata is not None,
            "db_alembic_version": backup_revision,
            "db_alembic_version_label": _revision_display_label(backup_revision),
            "current_db_alembic_version": current_revision,
            "current_db_alembic_version_label": _revision_display_label(current_revision),
            "restorable_on_current_db": bool(metadata and compatibility.get("compatible")),
            "restore_compatibility": compatibility,
        })
    return backups


@router.get("/compatibility-map")
def get_backup_compatibility_map():
    revisions = _list_all_revisions_in_repo()
    revision_labels = {revision: _revision_display_label(revision) for revision in revisions}
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

@router.get("/download/{filename}")
def download_backup(filename: str):
    file_path = _safe_backup_path(filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File non trovato")
    return FileResponse(path=file_path, filename=file_path.name, media_type='application/octet-stream')

@router.delete("/delete/{filename}")
def delete_backup(filename: str, confirm: bool = Body(...)):
    if not confirm:
        raise HTTPException(status_code=400, detail="Cancellazione non confermata")

    file_path = _safe_backup_path(filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File non trovato")

    try:
        logger.info(f"Cancellazione avviata per il file: {file_path.name}")
        file_path.unlink()
        meta_path = _backup_meta_path(file_path)
        if meta_path.exists():
            meta_path.unlink()
        logger.info(f"Cancellazione completata per il file: {file_path.name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore durante la cancellazione: {str(e)}")

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

        if not file_path.exists():
            missing.append(filename)
            continue

        try:
            file_path.unlink()
            meta_path = _backup_meta_path(file_path)
            if meta_path.exists():
                meta_path.unlink()
            deleted.append(filename)
        except Exception:
            logger.exception(f"Errore durante la cancellazione del backup {filename}")
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
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File non trovato")

    if payload.mode == "advanced" and payload.overwrite_users_roles and not payload.overwrite_admin:
        raise HTTPException(
            status_code=400,
            detail="Per sovrascrivere utenti/ruoli e mantenere consistenza è necessario abilitare anche overwrite_admin",
        )

    metadata = _read_backup_metadata(file_path)
    if not metadata or not metadata.get("db_alembic_version"):
        raise HTTPException(status_code=400, detail="Backup privo di metadati versione, restore bloccato")

    current_db = SessionLocal()
    try:
        current_revision = _get_alembic_version(current_db)
    finally:
        current_db.close()

    backup_revision = metadata.get("db_alembic_version")
    compatibility = _evaluate_restore_compatibility(backup_revision, current_revision)

    if not compatibility.get("compatible"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Backup non ripristinabile su questo DB: versione backup={backup_revision} "
                f"versione corrente={current_revision}. Motivo: {compatibility.get('reason')}"
            ),
        )

    try:
        env = os.environ.copy()
        env["PGPASSWORD"] = os.getenv("POSTGRES_PASSWORD", "admin")

        include_tables = set(CORE_RESTORE_TABLES)
        include_tables.add("users")
        if payload.mode == "advanced" and payload.overwrite_users_roles:
            include_tables.add("roles")
        if payload.mode == "advanced" and payload.overwrite_settings:
            include_tables.add("settings")

        skip_admin_insert = not (payload.mode == "advanced" and payload.overwrite_users_roles and payload.overwrite_admin)

        restore_sql_path = BACKUP_DIR / f"tmp_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        _build_filtered_restore_sql(file_path, restore_sql_path, include_tables, skip_admin_insert)

        def run_restore():
            db = None
            try:
                logger.info(f"Restore avviato per il file: {filename}")
                # Esegui il comando di restore in un thread separato
                logger.info(f"Pulizia tabelle prima del restore...")
                db = SessionLocal()

                # Ordine child -> parent per minimizzare problemi FK
                for table_name in [
                    "shared_inventories",
                    "shared_inventory_groups",
                    "item_metadata_values",
                    "metadata_definition_assignments",
                    "filter_templates",
                    "item_versions",
                    "inventory_versions",
                    "item_barcodes",
                    "list_assignments",
                    "items",
                    "metadata_definitions",
                    "user_group_association",
                    "groups",
                    "inventories",
                ]:
                    _safe_delete_table(db, table_name)

                if payload.mode == "advanced" and payload.overwrite_users_roles and payload.overwrite_admin:
                    _nullify_foreign_keys_to_users(db)
                    _safe_delete_table(db, "users")
                    _safe_delete_table(db, "roles")
                else:
                    if _table_exists(db, "users"):
                        db.execute(text("DELETE FROM users WHERE username != 'admin'"))

                if payload.mode == "advanced" and payload.overwrite_settings:
                    _safe_delete_table(db, "settings")

                db.commit()
                logger.info(f"Pulizia completata. Avvio restore da {filename}")

                subprocess.run([
                    "psql",
                    "-U", os.getenv("POSTGRES_USER", "admin"),
                    "-h", os.getenv("POSTGRES_HOST", "db"),
                    "-d", os.getenv("POSTGRES_DB", "inventory"),
                    "-f", str(restore_sql_path)
                ], check=True, env=env)

                # Allinea tutte le sequence PK dopo il restore per evitare duplicate key.
                _sync_id_sequences(db)
                logger.info(f"Restore completato per il file: {filename}")
            except Exception as e:
                logger.error(f"Errore durante il restore: {str(e)}")
            finally:
                if db:
                    db.close()
                try:
                    if restore_sql_path.exists():
                        restore_sql_path.unlink()
                except Exception:
                    logger.warning(f"Impossibile eliminare file temporaneo restore {restore_sql_path.name}")

        threading.Thread(target=run_restore).start()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nel restore: {str(e)}")

    return {
        "message": "Restore avviato in background",
        "mode": payload.mode,
        "compatibility": compatibility,
    }

@router.post("/upload")
def upload_backup(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome file non fornito.")
    # Gli upload sono importazioni, anche quando il file proviene da un backup
    # automatico. Il prefisso li distingue dai backup creati localmente; il token
    # evita collisioni anche con upload ripetuti o nomi uguali.
    original_name = file.filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not original_name.endswith(".sql"):
        raise HTTPException(status_code=400, detail="Formato file non valido. Solo file .sql ammessi")
    original_name = original_name.lstrip(".") or "backup.sql"
    original_name = original_name[:120]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"uploaded_{timestamp}_{uuid.uuid4().hex}_{original_name}"
    file_path = _safe_backup_path(filename)

    try:
        with open(file_path, "wb") as buffer:
            buffer.write(file.file.read())
        logger.info(f"File di backup caricato: {file_path.name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore durante il caricamento del file: {str(e)}")

    return {"message": "Backup caricato correttamente", "filename": file_path.name}

@router.get("/schedule")
def get_backup_schedule(db: Session = Depends(get_db)):
    """Restituisce la configurazione della schedulazione backup."""
    frequency   = get_setting(db, "BACKUP_FREQUENCY")
    int_days    = get_setting(db, "BACKUP_INTERVAL_DAYS")
    int_hours   = get_setting(db, "BACKUP_INTERVAL_HOURS")
    int_minutes = get_setting(db, "BACKUP_INTERVAL_MINUTES")
    retention   = get_setting(db, "BACKUP_RETENTION")
    return {
        "BACKUP_FREQUENCY": frequency,
        "BACKUP_INTERVAL_DAYS": int_days,
        "BACKUP_INTERVAL_HOURS": int_hours,
        "BACKUP_INTERVAL_MINUTES": int_minutes,
        "BACKUP_RETENTION": retention
    }

@router.post("/schedule")
def set_backup_schedule(
    backup_frequency:   str = Body(..., embed=True),
    backup_int_days:    int = Body(..., embed=True),
    backup_int_hours:   int = Body(..., embed=True),
    backup_int_minutes: int = Body(..., embed=True),
    backup_retention:   int = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """Aggiorna o crea la configurazione della schedulazione backup."""
    set_setting(db, "BACKUP_FREQUENCY", str(backup_frequency))
    set_setting(db, "BACKUP_INTERVAL_DAYS", str(backup_int_days))
    set_setting(db, "BACKUP_INTERVAL_HOURS", str(backup_int_hours))
    set_setting(db, "BACKUP_INTERVAL_MINUTES", str(backup_int_minutes))
    set_setting(db, "BACKUP_RETENTION", str(backup_retention))

    try:
        from scheduler import start_scheduler as perform_start_scheduler
        perform_start_scheduler()
    except Exception as e:
        logger.error(f"Errore durante l'avvio dello scheduler: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Errore durante l'avvio dello scheduler: {str(e)}")
    
    return {"message": "Schedulazione aggiornata correttamente."}

@router.post("/schedule/trigger")
def trigger_backup_now(db: Session = Depends(get_db)):
    """Esegue immediatamente un backup manuale come se fosse schedulato."""
    try:
        from scheduler import scheduled_backup as perform_scheduled_backup
        perform_scheduled_backup()
        return {"message": "Backup schedulato avviato manualmente."}
    except Exception as e:
        logger.error(f"Errore durante il trigger manuale del backup: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Errore durante il trigger manuale del backup: {str(e)}")
