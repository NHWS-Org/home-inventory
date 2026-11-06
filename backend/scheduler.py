# backend/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from database import SessionLocal
from routes.backup import create_backup, BACKUP_DIR
from datetime import datetime, timezone, timedelta
from crud import get_setting, set_setting
import logging
import traceback
from models import ItemVersion, InventoryVersion, Item, Inventory, DeviceSession
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from telemetry_service import send_telemetry, telemetry_enabled

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _setting_int(db, key: str, default: int) -> int:
    setting = get_setting(db, key)
    raw_value = setting.value if setting else None
    if raw_value in (None, ""):
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        logger.warning(f"Valore setting non valido per {key}: {raw_value}. Uso default {default}.")
        return default

def cleanup_old_backups(retention_count: int):
    backups = sorted(BACKUP_DIR.glob("auto_*.hibackup"), key=lambda x: x.stat().st_mtime)
    if len(backups) > retention_count:
        deleted = 0
        for backup in backups[:-retention_count]:
            logger.info(f"Eliminazione backup scaduto: {backup.name}")
            backup.unlink()
            deleted += 1
        logger.info(f"Backup eliminati: {deleted}")

def cleanup_old_audit_versions():
    """Pulisce solo i log di audit orfani più vecchi di AUDIT_RETENTION_DAYS.

    Un record audit è considerato orfano quando l'entità principale non esiste più.
    Le versioni di entità ancora presenti non vengono mai eliminate da questa retention.
    """
    db = SessionLocal()
    try:
        retention_days = _setting_int(db, "AUDIT_RETENTION_DAYS", 90)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        # Elimina ItemVersion orfani precedenti alla data cutoff
        deleted_items = db.query(ItemVersion).filter(
            ItemVersion.changed_at < cutoff_date,
            ~ItemVersion.item_id.in_(db.query(Item.id))
        ).delete(synchronize_session=False)

        # Elimina InventoryVersion orfani precedenti alla data cutoff
        deleted_inventories = db.query(InventoryVersion).filter(
            InventoryVersion.changed_at < cutoff_date,
            ~InventoryVersion.inventory_id.in_(db.query(Inventory.id))
        ).delete(synchronize_session=False)

        db.commit()
        if deleted_items + deleted_inventories > 0:
            logger.info(f"Pulizia audit: {deleted_items} item versions + {deleted_inventories} inventory versions eliminate (>= {retention_days} giorni)")
    except Exception as e:
        logger.error(f"Errore nella pulizia audit: {traceback.format_exc()}")
    finally:
        db.close()


def cleanup_old_device_sessions():
    db = SessionLocal()
    try:
        setting = get_setting(db, "DEVICE_SESSION_RETENTION_DAYS")
        retention_days = int(setting.value) if setting else 30
        if retention_days <= 0:
            raise ValueError("DEVICE_SESSION_RETENTION_DAYS must be positive")
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retention_days)
        deleted = db.query(DeviceSession).filter(or_(
            DeviceSession.revoked_at < cutoff,
            DeviceSession.expires_at < cutoff,
        )).delete(synchronize_session=False)
        db.commit()
        if deleted:
            logger.info("Pulizia sessioni: %s sessioni terminate da oltre %s giorni eliminate", deleted, retention_days)
    except (ValueError, TypeError, OverflowError, SQLAlchemyError):
        db.rollback()
        logger.exception("Errore nella pulizia sessioni; nessuna eliminazione confermata")
    finally:
        db.close()


def scheduled_backup():
    logger.info("Backup automatico avviato...")
    db = SessionLocal()
    try:
        create_backup(db, "auto")
        set_setting(db, "BACKUP_LAST_RUN", datetime.now(timezone.utc))
        
        # Controllo della retention
        retention = _setting_int(db, "BACKUP_RETENTION", 10)
        cleanup_old_backups(retention)
        
        # Pulizia audit log
        cleanup_old_audit_versions()

    except Exception as e:
        logger.error(f"Errore nel backup automatico: {traceback.format_exc()}")
    finally:
        db.close()
    logger.info("Backup automatico completato.")

def scheduled_telemetry():
    db = SessionLocal()
    try:
        send_telemetry(db)
    except Exception:
        logger.error(f"Errore nella telemetria: {traceback.format_exc()}")
    finally:
        db.close()

def _schedule_telemetry():
    if not telemetry_enabled():
        return
    # Primo invio poco dopo l'avvio, poi una volta al giorno
    scheduler.add_job(
        scheduled_telemetry,
        trigger=IntervalTrigger(hours=24),
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
        id="telemetry_job",
        replace_existing=True,
    )
    logger.info("Telemetria anonima attiva (opt-in): invio giornaliero.")

def _ensure_scheduler_started():
    if scheduler.get_jobs() and not scheduler.running:
        scheduler.start()

def start_scheduler():
    db = SessionLocal()
    try:
        setting = get_setting(db, "BACKUP_FREQUENCY")
        frequency = ((setting.value if setting else "none") or "none").lower()
        interval_days = _setting_int(db, "BACKUP_INTERVAL_DAYS", 0)
        interval_hours = _setting_int(db, "BACKUP_INTERVAL_HOURS", 0)
        interval_minutes = _setting_int(db, "BACKUP_INTERVAL_MINUTES", 0)

        scheduler.remove_all_jobs()
        scheduler.add_job(
            cleanup_old_device_sessions,
            trigger=IntervalTrigger(hours=24),
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
            id="device_session_cleanup_job",
            replace_existing=True,
        )
        _schedule_telemetry()

        if frequency == "none":
            logger.info("Backup automatico disabilitato.")
            _ensure_scheduler_started()
            return

        if frequency == "hourly":
            scheduler.add_job(
                scheduled_backup,
                trigger="cron",
                minute=interval_minutes,
                id="backup_job",
                replace_existing=True,
            )
            logger.info(f"Scheduler avviato. Backup ogni ora al minuto {interval_minutes:02}.")
        elif frequency == "daily":
            scheduler.add_job(
                scheduled_backup,
                trigger="cron",
                hour=interval_hours,
                minute=interval_minutes,
                id="backup_job",
                replace_existing=True,
            )
            logger.info(f"Scheduler avviato. Backup giornaliero alle {interval_hours:02}:{interval_minutes:02}.")
        elif frequency == "weekly":
            scheduler.add_job(
                scheduled_backup,
                trigger="cron",
                day_of_week=interval_days,
                hour=interval_hours,
                minute=interval_minutes,
                id="backup_job",
                replace_existing=True,
            )
            logger.info(f"Scheduler avviato. Backup settimanale il giorno {interval_days} alle {interval_hours:02}:{interval_minutes:02}.")
        else:
            logger.warning(f"Frequenza di backup non riconosciuta: {frequency}")
            _ensure_scheduler_started()
            return

        if not scheduler.running:
            scheduler.start()

    except Exception as e:
        logger.error(f"Errore durante l'avvio del scheduler: {traceback.format_exc()}")
    finally:
        db.close()