"""Run with python -m notification_worker; never imported by the API."""

import argparse
import logging
import json
import os
from pathlib import Path
import signal
import tempfile
from threading import Event
import time

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal
from models import NotificationEvent
from notification_outbox import LEASE_SECONDS, claim_event, process_claim

logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path(tempfile.gettempdir()) / "home-inventory-notification-worker.json"
HEARTBEAT_MAX_AGE_SECONDS = LEASE_SECONDS * 2


def write_heartbeat(path: Path = HEARTBEAT_PATH) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"pid": os.getpid(), "updated_at": time.monotonic()}))
    temporary.replace(path)


def check_health(factory=SessionLocal, path: Path = HEARTBEAT_PATH) -> bool:
    try:
        heartbeat = json.loads(path.read_text())
        pid = heartbeat["pid"]
        updated_at = heartbeat["updated_at"]
        if type(pid) is not int or pid <= 0 or type(updated_at) not in (int, float):
            raise ValueError("Invalid heartbeat")
        age = time.monotonic() - updated_at
        if not 0 <= age <= HEARTBEAT_MAX_AGE_SECONDS:
            raise ValueError("Stale heartbeat")
        os.kill(pid, 0)
        with factory() as db:
            db.execute(select(NotificationEvent.id).limit(1))
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError) as exc:
        logger.error("Notification worker healthcheck failed (%s)", type(exc).__name__)
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Database-backed notification outbox worker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Process at most one event and exit")
    mode.add_argument("--status", action="store_true", help="Report queue counts without processing")
    mode.add_argument("--healthcheck", action="store_true", help="Check worker heartbeat and database")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.healthcheck:
        raise SystemExit(0 if check_health() else 1)
    if args.status:
        with SessionLocal() as db:
            counts = dict(db.execute(select(
                NotificationEvent.status, func.count(),
            ).group_by(NotificationEvent.status)).all())
        logger.info("Notification queue counts: %s", counts)
        return
    logger.info("Notification rules enabled: database inbox only, no external sends")
    stop = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda _signum, _frame: stop.set())
    HEARTBEAT_PATH.unlink(missing_ok=True)
    try:
        while not stop.is_set():
            claim = claim_event(SessionLocal)
            if claim is not None:
                succeeded = process_claim(SessionLocal, claim)
                logger.info(
                    "Notification event %s processing %s",
                    claim.event_id, "completed" if succeeded else "not completed",
                )
                if args.once and not succeeded:
                    raise SystemExit(1)
            write_heartbeat()
            if args.once:
                return
            if claim is None:
                stop.wait(2)
    finally:
        HEARTBEAT_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
