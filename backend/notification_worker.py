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

logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path(tempfile.gettempdir()) / "home-inventory-notification-worker.json"
HEARTBEAT_MAX_AGE_SECONDS = 120


def write_heartbeat(path: Path = HEARTBEAT_PATH) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"pid": os.getpid(), "updated_at": time.monotonic()}))
    temporary.replace(path)


def check_health(factory=None, path: Path = HEARTBEAT_PATH) -> bool:
    started = time.monotonic()
    logger.info("Healthcheck: checking worker heartbeat")
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
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.error("Notification worker healthcheck failed at heartbeat (%s)", type(exc).__name__)
        return False
    logger.info("Healthcheck: checking database")
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        if factory is None:
            from database import SessionLocal

            factory = SessionLocal
        with factory() as db:
            db.execute(text("SELECT id FROM notification_events LIMIT 1"))
            db.execute(text("SELECT id FROM push_deliveries LIMIT 1"))
    except (OSError, ValueError, SQLAlchemyError) as exc:
        logger.error("Notification worker healthcheck failed at database (%s)", type(exc).__name__)
        return False
    logger.info("Notification worker healthcheck passed in %.3fs", time.monotonic() - started)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Database-backed notification outbox worker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Process at most one event and exit")
    mode.add_argument("--status", action="store_true", help="Report queue counts without processing")
    mode.add_argument("--healthcheck", action="store_true", help="Check worker heartbeat and database")
    mode.add_argument("--reset-push", action="store_true", help="Discard subscriptions and push work after an offline database restore")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.healthcheck:
        raise SystemExit(0 if check_health() else 1)
    from sqlalchemy import func, select
    from database import SessionLocal
    from models import NotificationEvent, PushDelivery, PushSubscription

    if args.reset_push:
        with SessionLocal.begin() as db:
            deliveries = db.query(PushDelivery).delete()
            subscriptions = db.query(PushSubscription).delete()
        logger.warning("Web Push reset: %s deliveries, %s subscriptions removed", deliveries, subscriptions)
        return
    if args.status:
        with SessionLocal() as db:
            counts = dict(db.execute(select(
                NotificationEvent.status, func.count(),
            ).group_by(NotificationEvent.status)).all())
            push_counts = dict(db.execute(select(
                PushDelivery.status, func.count(),
            ).group_by(PushDelivery.status)).all())
        logger.info("Notification queue counts: %s", counts)
        logger.info("Web Push queue counts: %s", push_counts)
        return
    from notification_outbox import claim_event, process_claim
    from push_config import load_push_config
    from web_push import claim_push, process_push

    config = load_push_config()
    logger.info(
        "Notification worker started (pid=%s); personal notifications enabled; Web Push %s",
        os.getpid(), "enabled" if config else "disabled",
    )
    stop = Event()

    def request_stop(signum, _frame):
        logger.info("Notification worker received signal %s; stopping", signum)
        stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, request_stop)
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
            push_claim = claim_push(SessionLocal)
            if push_claim is not None:
                if not process_push(SessionLocal, push_claim) and args.once:
                    raise SystemExit(1)
            write_heartbeat()
            if args.once:
                return
            if claim is None and push_claim is None:
                stop.wait(2)
    finally:
        HEARTBEAT_PATH.unlink(missing_ok=True)
        logger.info("Notification worker stopped (pid=%s)", os.getpid())


if __name__ == "__main__":
    main()
