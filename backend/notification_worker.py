"""Run with python -m notification_worker; never imported by the API."""

import argparse
import logging
import signal
from threading import Event

from sqlalchemy import func, select

from database import SessionLocal
from models import NotificationEvent
from notification_outbox import claim_event, process_claim

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Database-backed notification outbox worker")
    parser.add_argument("--once", action="store_true", help="Process at most one event and exit")
    parser.add_argument("--status", action="store_true", help="Report queue counts without processing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.status:
        with SessionLocal() as db:
            counts = dict(db.execute(select(
                NotificationEvent.status, func.count(),
            ).group_by(NotificationEvent.status)).all())
        logger.info("Notification queue counts: %s", counts)
        return
    logger.warning("Phase 2: rules are not enabled; queued events retry then fail, no external sends")
    stop = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda _signum, _frame: stop.set())
    while not stop.is_set():
        claim = claim_event(SessionLocal)
        if claim is not None:
            succeeded = process_claim(SessionLocal, claim)
            if args.once and not succeeded:
                raise SystemExit(1)
        if args.once:
            return
        if claim is None:
            stop.wait(2)


if __name__ == "__main__":
    main()
