from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from models import Base, Notification, NotificationEvent, Role, User
from notification_contracts import ChecklistCompletedData
from notification_outbox import (
    MAX_ATTEMPTS, RetryableNotificationError, claim_event, enqueue_event, process_claim,
)

NOW = datetime(2026, 11, 5, 12)


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}", connect_args={"timeout": 15})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(Role(id=1, name="viewer"))
        db.flush()
        db.add(User(id=1, username="member", role_id=1))
    yield factory
    engine.dispose()


def enqueue(factory, **kwargs):
    with factory.begin() as db:
        record = enqueue_event(
            db, ChecklistCompletedData(inventory_id=1), actor_id=1, now=NOW, **kwargs,
        )
        db.flush()
        return record.id


def inbox_handler(db, record):
    db.add(Notification(event_id=record.id, user_id=1))


def test_enqueue_does_not_commit_domain_change(factory):
    with factory() as db:
        db.get(User, 1).username = "changed"
        enqueue_event(db, ChecklistCompletedData(inventory_id=1), actor_id=1, now=NOW)
        db.flush()
        db.rollback()
    with factory() as db:
        assert db.get(User, 1).username == "member"
        assert db.scalars(select(NotificationEvent)).all() == []


def test_success_is_atomic_and_repeated_claim_does_not_duplicate(factory):
    event_id = enqueue(factory)
    claim = claim_event(factory, now=NOW)
    assert claim.event_id == event_id
    assert process_claim(factory, claim, inbox_handler, now=NOW)
    assert not process_claim(factory, claim, inbox_handler, now=NOW)
    assert claim_event(factory, now=NOW) is None
    with factory() as db:
        record = db.get(NotificationEvent, event_id)
        assert record.status == "completed"
        assert record.attempts == 1
        assert record.lease_token is None
        assert len(db.scalars(select(Notification)).all()) == 1


def test_recover_crash_and_fence_stale_worker(factory):
    enqueue(factory)
    old_claim = claim_event(factory, now=NOW)
    assert claim_event(factory, now=NOW + timedelta(seconds=59)) is None
    new_claim = claim_event(factory, now=NOW + timedelta(seconds=61))
    assert new_claim is not None
    assert new_claim.token != old_claim.token
    assert not process_claim(factory, old_claim, inbox_handler, now=NOW + timedelta(seconds=62))
    assert process_claim(factory, new_claim, inbox_handler, now=NOW + timedelta(seconds=62))


def test_retry_rolls_back_effects_and_is_bounded(factory, caplog):
    event_id = enqueue(factory)

    def failing(db, record):
        inbox_handler(db, record)
        db.flush()
        raise RetryableNotificationError("private content must never enter logs")

    current = NOW
    for attempt in range(1, MAX_ATTEMPTS + 1):
        claim = claim_event(factory, now=current)
        assert claim is not None
        assert not process_claim(factory, claim, failing, now=current)
        with factory() as db:
            record = db.get(NotificationEvent, event_id)
            assert record.attempts == attempt
            assert record.status == ("failed" if attempt == MAX_ATTEMPTS else "pending")
            assert db.scalars(select(Notification)).all() == []
            assert record.available_at == current + timedelta(seconds=30 * 2 ** (attempt - 1))
            assert claim_event(factory, now=current) is None
            current = record.available_at
    assert "private content" not in caplog.text
    assert claim_event(factory, now=current) is None


@pytest.mark.parametrize("changes", [
    {"schema_version": 2},
    {"payload": {"event_type": "unknown"}},
])
def test_bad_event_fails_permanently_without_handler(factory, changes):
    event_id = enqueue(factory)
    with factory.begin() as db:
        record = db.get(NotificationEvent, event_id)
        for key, value in changes.items():
            setattr(record, key, value)
    claim = claim_event(factory, now=NOW)
    assert not process_claim(factory, claim, inbox_handler, now=NOW)
    with factory() as db:
        assert db.get(NotificationEvent, event_id).status == "failed"
        assert db.scalars(select(Notification)).all() == []


def test_expired_and_crash_exhausted_events_never_run(factory):
    expired = enqueue(factory)
    exhausted = enqueue(factory)
    with factory.begin() as db:
        db.get(NotificationEvent, expired).expires_at = NOW
        record = db.get(NotificationEvent, exhausted)
        record.status = "processing"
        record.attempts = MAX_ATTEMPTS
        record.leased_until = NOW
        record.lease_token = str(uuid4())
    assert claim_event(factory, now=NOW) is None
    with factory() as db:
        assert all(record.status == "failed" for record in db.scalars(select(NotificationEvent)))


def test_two_workers_claim_event_once(factory):
    enqueue(factory)
    barrier = Barrier(2)

    def claim():
        barrier.wait()
        return claim_event(factory, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    assert sum(claim is not None for claim in claims) == 1


def test_concurrent_processing_is_fenced(factory):
    enqueue(factory)
    claim = claim_event(factory, now=NOW)
    barrier = Barrier(2)

    def process():
        barrier.wait()
        return process_claim(factory, claim, inbox_handler, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: process(), range(2)))
    assert sorted(results) == [False, True]
    with factory() as db:
        assert len(db.scalars(select(Notification)).all()) == 1


def test_duplicate_event_key_rejected_in_transaction(factory):
    key = str(uuid4())
    enqueue(factory, event_key=key)
    with pytest.raises(IntegrityError):
        enqueue(factory, event_key=key)


def test_phase_two_without_rules_retries_explicitly(factory, caplog):
    event_id = enqueue(factory)
    claim = claim_event(factory, now=NOW)
    assert not process_claim(factory, claim, now=NOW)
    assert "temporary_processing_error" in caplog.text
    with factory() as db:
        assert db.get(NotificationEvent, event_id).status == "pending"


def test_restore_discards_pending_events_even_for_preserved_admin(factory):
    from routes.backup import RestoreRequest, _restore_backup_rows

    event_id = enqueue(factory)
    with factory.begin() as db:
        db.get(User, 1).username = "admin"
        db.add(Notification(event_id=event_id, user_id=1))
    with factory.begin() as db:
        _restore_backup_rows(db, {
            "notification_events": [{
                "id": 99, "event_key": str(uuid4()), "payload": {},
                "status": "pending", "attempts": 0,
            }],
        }, RestoreRequest(confirm=True), {})
    assert claim_event(factory, now=NOW) is None
    with factory() as db:
        assert db.scalars(select(NotificationEvent)).all() == []
        assert db.scalars(select(Notification)).all() == []
        assert db.get(User, 1).username == "admin"


def test_restore_rollback_preserves_queue(factory):
    from routes.backup import RestoreRequest, _restore_backup_rows

    event_id = enqueue(factory)
    with factory() as db:
        _restore_backup_rows(db, {}, RestoreRequest(confirm=True), {})
        db.rollback()
    with factory() as db:
        assert db.get(NotificationEvent, event_id).status == "pending"


def test_worker_migration_downgrade_preserves_events_and_inbox(factory):
    from test_notification_foundations import MIGRATION, load_migration

    migration = load_migration(
        MIGRATION.parent / "b2c3d4e5f6a7_notification_worker_leases.py",
    )
    event_id = enqueue(factory)
    with factory.begin() as db:
        db.add(Notification(event_id=event_id, user_id=1))
    with factory.begin() as db:
        with Operations.context(MigrationContext.configure(db.connection())):
            migration.downgrade()
            migration.upgrade()
    with factory() as db:
        assert db.get(NotificationEvent, event_id).status == "pending"
        assert len(db.scalars(select(Notification)).all()) == 1


def test_worker_once_returns_failure_for_unconfigured_rules(factory, monkeypatch):
    import notification_worker

    with factory.begin() as db:
        enqueue_event(db, ChecklistCompletedData(inventory_id=1), actor_id=1)
    monkeypatch.setattr(notification_worker, "SessionLocal", factory)
    monkeypatch.setattr("sys.argv", ["notification_worker", "--once"])
    monkeypatch.setattr(notification_worker.signal, "signal", lambda *args: None)
    with pytest.raises(SystemExit) as result:
        notification_worker.main()
    assert result.value.code == 1


def test_worker_status_does_not_claim_pending_event(factory, monkeypatch, caplog):
    import notification_worker

    event_id = enqueue(factory)
    monkeypatch.setattr(notification_worker, "SessionLocal", factory)
    monkeypatch.setattr("sys.argv", ["notification_worker", "--status"])
    with caplog.at_level("INFO"):
        notification_worker.main()
    assert "pending" in caplog.text
    with factory() as db:
        assert db.get(NotificationEvent, event_id).attempts == 0
