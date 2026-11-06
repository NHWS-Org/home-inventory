from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from crud import get_setting, set_setting
from dependencies import get_db, get_current_user, initialize_settings
from models import Base, DeviceSession, Role, SecurityAudit, User
from routes.settings import router
import scheduler


NOW = datetime(2026, 11, 6, 12, 0)


@pytest.fixture
def retention(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(Role(id=1, name="admin"))
        db.flush()
        db.add(User(id=1, username="admin", hashed_password="unused", role_id=1))
    monkeypatch.setattr(scheduler, "SessionLocal", factory)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.replace(tzinfo=timezone.utc) if tz else NOW

    monkeypatch.setattr(scheduler, "datetime", Clock)
    yield factory
    engine.dispose()


def add_session(db, name, *, expires, revoked=None, created=NOW - timedelta(days=100)):
    db.add(DeviceSession(
        session_token_id=name, user_id=1, created_at=created,
        expires_at=expires, revoked_at=revoked,
    ))


def session_names(factory):
    with factory() as db:
        return set(db.scalars(select(DeviceSession.session_token_id)))


def test_default_cleanup_keeps_active_recent_and_boundary_sessions_and_audit(retention):
    with retention.begin() as db:
        add_session(db, "active-old-login", expires=NOW + timedelta(days=1))
        add_session(db, "expired-old", expires=NOW - timedelta(days=31))
        add_session(db, "revoked-old", expires=NOW + timedelta(days=20), revoked=NOW - timedelta(days=31))
        add_session(db, "expired-before-revoked", expires=NOW - timedelta(days=31), revoked=NOW - timedelta(days=1))
        add_session(db, "expired-recent", expires=NOW - timedelta(days=29))
        add_session(db, "revoked-recent", expires=NOW + timedelta(days=1), revoked=NOW - timedelta(days=29))
        add_session(db, "expiry-boundary", expires=NOW - timedelta(days=30))
        add_session(db, "revoked-boundary", expires=NOW + timedelta(days=1), revoked=NOW - timedelta(days=30))
        add_session(db, "expiry-before-boundary", expires=NOW - timedelta(days=30, microseconds=1))
        add_session(db, "revoked-before-boundary", expires=NOW + timedelta(days=1),
                    revoked=NOW - timedelta(days=30, microseconds=1))
        db.add(SecurityAudit(
            actor_id=1, actor_username="admin", action="revoke_sessions", outcome="succeeded",
            created_at=NOW - timedelta(days=100), revoked_before=1, sessions_revoked=3,
        ))
    scheduler.cleanup_old_device_sessions()
    assert session_names(retention) == {
        "active-old-login", "expired-recent", "revoked-recent", "expiry-boundary", "revoked-boundary",
    }
    with retention() as db:
        assert db.scalars(select(SecurityAudit)).one().revoked_before == 1
    scheduler.cleanup_old_device_sessions()
    assert len(session_names(retention)) == 5


def test_cleanup_reads_changed_retention_without_restart(retention):
    with retention() as db:
        set_setting(db, "DEVICE_SESSION_RETENTION_DAYS", "60", True)
        add_session(db, "expired", expires=NOW - timedelta(days=31))
        db.commit()
    scheduler.cleanup_old_device_sessions()
    assert session_names(retention) == {"expired"}
    with retention() as db:
        set_setting(db, "DEVICE_SESSION_RETENTION_DAYS", "7")
    scheduler.cleanup_old_device_sessions()
    assert session_names(retention) == set()


@pytest.mark.parametrize("value", ["0", "-1", "invalid", "1.5", "", "9999999999999999999999999"])
def test_invalid_persisted_retention_logs_error_without_deleting(retention, caplog, value):
    with retention() as db:
        set_setting(db, "DEVICE_SESSION_RETENTION_DAYS", value)
        add_session(db, "expired", expires=NOW - timedelta(days=100))
        db.commit()
    scheduler.cleanup_old_device_sessions()
    assert session_names(retention) == {"expired"}
    assert "Errore nella pulizia sessioni" in caplog.text


def test_setting_bootstrap_is_protected_and_preserves_custom_value(retention):
    with retention() as db:
        initialize_settings(db)
        setting = get_setting(db, "DEVICE_SESSION_RETENTION_DAYS")
        assert setting.value == "30" and setting.protected
        setting.value = "14"
        setting.protected = False
        db.commit()
        initialize_settings(db)
        db.refresh(setting)
        assert setting.value == "14" and setting.protected


def test_cleanup_rolls_back_database_failure(retention, monkeypatch, caplog):
    with retention.begin() as db:
        add_session(db, "expired", expires=NOW - timedelta(days=40))

    def failing_commit(db):
        raise OperationalError("commit failed", {}, Exception())

    monkeypatch.setattr(retention.class_, "commit", failing_commit)
    scheduler.cleanup_old_device_sessions()
    assert session_names(retention) == {"expired"}
    assert "nessuna eliminazione confermata" in caplog.text


def test_setting_api_validates_retention_and_prevents_deletion(retention):
    with retention() as db:
        initialize_settings(db)
    app = FastAPI()
    app.include_router(router, prefix="/settings")

    def database():
        with retention() as db:
            yield db

    def admin():
        with retention() as db:
            user = db.get(User, 1)
            user.role
            return user

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = admin
    client = TestClient(app)
    for value in ("0", "-7", "1.5", "", "invalid", "999999999999999999999"):
        response = client.post("/settings/settings", json={
            "key": "DEVICE_SESSION_RETENTION_DAYS", "value": value,
        })
        assert response.status_code == 422
    with retention() as db:
        assert get_setting(db, "DEVICE_SESSION_RETENTION_DAYS").value == "30"
    assert client.post("/settings/settings", json={
        "key": "DEVICE_SESSION_RETENTION_DAYS", "value": "14",
    }).status_code == 200
    assert client.delete("/settings/settings/DEVICE_SESSION_RETENTION_DAYS").status_code == 403
    entry = client.get("/settings/settings/DEVICE_SESSION_RETENTION_DAYS").json()
    assert entry["value"] == "14" and entry["protected"]


@pytest.mark.parametrize("frequency", ["none", "daily", "hourly", "unrecognized"])
def test_cleanup_scheduled_independently_of_backups_and_telemetry(retention, monkeypatch, frequency):
    jobs = BackgroundScheduler()
    started = []
    monkeypatch.setattr(scheduler, "scheduler", jobs)
    monkeypatch.setattr(jobs, "start", lambda: started.append(True))
    monkeypatch.setenv("TELEMETRY_ENABLED", "false")
    with retention() as db:
        set_setting(db, "BACKUP_FREQUENCY", frequency)
    scheduler.start_scheduler()
    job = jobs.get_job("device_session_cleanup_job")
    assert job is not None
    assert job.func is scheduler.cleanup_old_device_sessions
    assert job.trigger.interval == timedelta(hours=24)
    assert job.next_run_time == NOW.replace(tzinfo=timezone.utc) + timedelta(seconds=60)
    assert started == [True]
