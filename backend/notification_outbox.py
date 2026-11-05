"""Transactional database work only; external delivery belongs in a separate outbox."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from models import NotificationEvent
from notification_contracts import NotificationEventData, notification_event_adapter

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
LEASE_SECONDS = 60
RETRY_SECONDS = 30


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RetryableNotificationError(Exception):
    """A temporary processing failure; no exception text is persisted."""


class PermanentNotificationError(Exception):
    """An event that cannot be processed."""


@dataclass(frozen=True)
class Claim:
    event_id: int
    token: str


def enqueue_event(
    db: Session,
    data: NotificationEventData,
    *,
    actor_id: int | None,
    event_key: str | None = None,
    now: datetime | None = None,
) -> NotificationEvent:
    """Stage an event without flushing or committing the caller's transaction."""
    data = notification_event_adapter.validate_python(data)
    key = str(uuid4()) if event_key is None else str(UUID(event_key))
    created = now or utcnow()
    record = NotificationEvent(
        event_key=key,
        schema_version=1,
        actor_id=actor_id,
        payload=data.model_dump(mode="json"),
        created_at=created,
        available_at=created,
        expires_at=created + timedelta(days=7),
    )
    db.add(record)
    return record


def claim_event(factory: sessionmaker, *, now: datetime | None = None) -> Claim | None:
    current = now or utcnow()
    eligible = or_(
        and_(NotificationEvent.status == "pending", NotificationEvent.available_at <= current),
        and_(NotificationEvent.status == "processing", NotificationEvent.leased_until <= current),
    )
    with factory.begin() as db:
        terminal = db.execute(update(NotificationEvent).where(
            eligible,
            or_(NotificationEvent.attempts >= MAX_ATTEMPTS, NotificationEvent.expires_at <= current),
        ).values(
            status="failed", lease_token=None, leased_until=None, last_error="expired_or_exhausted",
        ))
        if terminal.rowcount:
            logger.warning("Notification events expired or exhausted: %s", terminal.rowcount)
        event_id = db.scalar(select(NotificationEvent.id).where(
            eligible,
            NotificationEvent.attempts < MAX_ATTEMPTS,
            or_(NotificationEvent.expires_at.is_(None), NotificationEvent.expires_at > current),
        ).order_by(NotificationEvent.id).limit(1))
        if event_id is None:
            return None
        token = str(uuid4())
        result = db.execute(update(NotificationEvent).where(
            NotificationEvent.id == event_id, eligible,
        ).values(
            status="processing", lease_token=token,
            leased_until=current + timedelta(seconds=LEASE_SECONDS),
            attempts=NotificationEvent.attempts + 1,
        ))
        return Claim(event_id, token) if result.rowcount == 1 else None


def rules_not_available(db: Session, event: NotificationEvent) -> None:
    raise RetryableNotificationError("Rules are introduced in phase 3")


def process_claim(
    factory: sessionmaker,
    claim: Claim,
    handler: Callable[[Session, NotificationEvent], None] = rules_not_available,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or utcnow()
    fence = (
        NotificationEvent.id == claim.event_id,
        NotificationEvent.status == "processing",
        NotificationEvent.lease_token == claim.token,
        NotificationEvent.leased_until > current,
    )
    try:
        with factory.begin() as db:
            # The write fences SQLite and row-locking databases for the entire handler transaction.
            if db.execute(update(NotificationEvent).where(*fence).values(
                lease_token=claim.token,
            )).rowcount != 1:
                return False
            record = db.scalars(select(NotificationEvent).where(
                NotificationEvent.id == claim.event_id,
            )).one()
            if record.schema_version != 1:
                raise PermanentNotificationError("Unsupported schema")
            notification_event_adapter.validate_python(record.payload)
            if record.expires_at is not None and record.expires_at <= current:
                raise PermanentNotificationError("Expired event")
            handler(db, record)
            record.status = "completed"
            record.lease_token = None
            record.leased_until = None
            record.last_error = None
        return True
    except Exception as exc:
        # Rollback all handler effects before recording failure in a separate transaction.
        retryable = isinstance(exc, (RetryableNotificationError, OperationalError))
        code = "temporary_processing_error" if retryable else "permanent_processing_error"
        logger.error("Notification event %s failed (%s, %s)", claim.event_id, code, type(exc).__name__)
        with factory.begin() as db:
            record = db.scalar(select(NotificationEvent).where(
                NotificationEvent.id == claim.event_id,
                NotificationEvent.status == "processing",
                NotificationEvent.lease_token == claim.token,
            ).with_for_update())
            if record is not None:
                db.execute(update(NotificationEvent).where(
                    NotificationEvent.id == claim.event_id,
                    NotificationEvent.status == "processing",
                    NotificationEvent.lease_token == claim.token,
                ).values(
                    status="pending" if retryable and record.attempts < MAX_ATTEMPTS else "failed",
                    available_at=current + timedelta(
                        seconds=RETRY_SECONDS * 2 ** (record.attempts - 1),
                    ),
                    lease_token=None, leased_until=None, last_error=code,
                ))
        return False
