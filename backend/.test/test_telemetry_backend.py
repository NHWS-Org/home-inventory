import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import telemetry_service
from database import Base
from models import Inventory, Item, Role, User


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    role = Role(name="admin")
    session.add(role)
    session.commit()
    user = User(username="admin", hashed_password="x", role_id=role.id)
    session.add(user)
    session.commit()
    session.add_all(
        [
            Inventory(name="Garage", type="INVENTORY", owner_id=user.id),
            Inventory(name="Cantina", type="INVENTORY", owner_id=user.id),
            Inventory(name="Spesa", type="CHECKLIST", owner_id=user.id),
        ]
    )
    session.commit()
    yield session
    session.close()


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_disabled_by_default(db, monkeypatch):
    monkeypatch.delenv("TELEMETRY_ENABLED", raising=False)
    monkeypatch.setenv("TELEMETRY_URL", "https://example.test/ping")
    called = []
    monkeypatch.setattr(telemetry_service.urllib.request, "urlopen", lambda *a, **k: called.append(1))

    assert telemetry_service.send_telemetry(db) is False
    assert called == []


def test_enabled_without_url_sends_nothing(db, monkeypatch):
    monkeypatch.setenv("TELEMETRY_ENABLED", "true")
    monkeypatch.delenv("TELEMETRY_URL", raising=False)
    monkeypatch.setattr(telemetry_service, "DEFAULT_TELEMETRY_URL", "")
    called = []
    monkeypatch.setattr(telemetry_service.urllib.request, "urlopen", lambda *a, **k: called.append(1))

    assert telemetry_service.send_telemetry(db) is False
    assert called == []


def test_default_url_is_used_without_env(db, monkeypatch):
    monkeypatch.setenv("TELEMETRY_ENABLED", "true")
    monkeypatch.delenv("TELEMETRY_URL", raising=False)
    monkeypatch.setattr(telemetry_service, "DEFAULT_TELEMETRY_URL", "https://default.test/ping")
    urls = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(telemetry_service.urllib.request, "urlopen", fake_urlopen)

    assert telemetry_service.send_telemetry(db) is True
    assert urls == ["https://default.test/ping"]


def test_payload_contains_only_expected_fields(db, monkeypatch):
    monkeypatch.setenv("API_VERSION", "1.4.0")
    payload = telemetry_service.build_payload(db)

    assert set(payload) == {"id", "version", "channel", "inventories", "last_activity"}
    assert payload["version"] == "1.4.0"
    assert payload["inventories"] == 2  # le checklist non contano
    assert payload["last_activity"] is not None


def test_instance_id_is_stable(db):
    assert telemetry_service.get_instance_id(db) == telemetry_service.get_instance_id(db)


def test_instance_id_env_override(db, monkeypatch):
    monkeypatch.setenv("TELEMETRY_INSTANCE_ID", "custom-instance-id-123")
    assert telemetry_service.get_instance_id(db) == "custom-instance-id-123"


def test_last_activity_is_none_without_data():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        assert telemetry_service._last_activity(session) is None
    finally:
        session.close()


def test_send_posts_json(db, monkeypatch):
    monkeypatch.setenv("TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_URL", "https://example.test/ping")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr(telemetry_service.urllib.request, "urlopen", fake_urlopen)

    assert telemetry_service.send_telemetry(db) is True
    assert captured["url"] == "https://example.test/ping"
    assert captured["method"] == "POST"
    assert set(captured["body"]) == {"id", "version", "channel", "inventories", "last_activity"}


def test_network_errors_are_swallowed(db, monkeypatch):
    monkeypatch.setenv("TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_URL", "https://example.test/ping")

    def failing_urlopen(*args, **kwargs):
        raise telemetry_service.urllib.error.URLError("offline")

    monkeypatch.setattr(telemetry_service.urllib.request, "urlopen", failing_urlopen)

    assert telemetry_service.send_telemetry(db) is False


def test_item_activity_updates_last_activity(db):
    inventory = db.query(Inventory).filter_by(type="INVENTORY").first()
    db.add(Item(name="Piselli", quantity=1, inventory_id=inventory.id))
    db.commit()

    assert telemetry_service._last_activity(db).endswith("+00:00")


def test_scheduler_registers_telemetry_job_when_backups_disabled(db, monkeypatch):
    import scheduler

    monkeypatch.setenv("TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_URL", "https://example.test/ping")
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    try:
        scheduler.start_scheduler()
        assert [job.id for job in scheduler.scheduler.get_jobs()] == ["telemetry_job"]
        assert scheduler.scheduler.running
    finally:
        scheduler.scheduler.remove_all_jobs()
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown(wait=False)


def test_scheduler_has_no_telemetry_job_by_default(db, monkeypatch):
    import scheduler

    monkeypatch.delenv("TELEMETRY_ENABLED", raising=False)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    scheduler.start_scheduler()
    assert scheduler.scheduler.get_jobs() == []


PUBLIC_STATS = {
    "active_installations": 12,
    "active_window_days": 30,
    "countries": [{"country": "IT", "n": 9}, {"country": "DE", "n": 3}],
    "versions": [{"version": "1.4.0", "n": 10}, {"version": "1.3.1", "n": 2}],
    "channels": [{"channel": "release", "n": 11}, {"channel": "dev", "n": 1}],
}


class FakeJsonResponse(FakeResponse):
    def __init__(self, payload):
        self.payload = payload

    def read(self, _size=-1):
        return json.dumps(self.payload).encode()


@pytest.fixture
def clean_about_cache():
    telemetry_service._about_cache.update(fetched_at=0.0, ttl=0, data=None)
    yield
    telemetry_service._about_cache.update(fetched_at=0.0, ttl=0, data=None)


def test_public_stats_url_is_derived_from_ping_url(monkeypatch):
    monkeypatch.setenv("TELEMETRY_URL", "https://t.example.test/ping")
    assert telemetry_service.public_stats_url() == "https://t.example.test/public-stats"
    monkeypatch.setenv("TELEMETRY_URL", "https://t.example.test/")
    assert telemetry_service.public_stats_url() == "https://t.example.test/public-stats"


def test_public_stats_unavailable_without_url(monkeypatch, clean_about_cache):
    monkeypatch.delenv("TELEMETRY_URL", raising=False)
    monkeypatch.setattr(telemetry_service, "DEFAULT_TELEMETRY_URL", "")
    assert telemetry_service.get_public_stats() is None


def test_public_stats_are_fetched_and_cached(monkeypatch, clean_about_cache):
    monkeypatch.setenv("TELEMETRY_URL", "https://t.example.test/ping")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        assert request.data is None  # sola GET, nessun dato inviato
        return FakeJsonResponse(PUBLIC_STATS)

    monkeypatch.setattr(telemetry_service.urllib.request, "urlopen", fake_urlopen)

    assert telemetry_service.get_public_stats() == PUBLIC_STATS
    assert telemetry_service.get_public_stats() == PUBLIC_STATS
    assert calls == ["https://t.example.test/public-stats"]


def test_public_stats_can_be_disabled(monkeypatch, clean_about_cache):
    monkeypatch.setenv("TELEMETRY_URL", "https://t.example.test/ping")
    monkeypatch.setenv("ABOUT_STATS_ENABLED", "false")
    called = []
    monkeypatch.setattr(telemetry_service.urllib.request, "urlopen", lambda *a, **k: called.append(1))

    assert telemetry_service.get_public_stats() is None
    assert called == []


def test_public_stats_failures_and_bad_payloads_return_none(monkeypatch, clean_about_cache):
    monkeypatch.setenv("TELEMETRY_URL", "https://t.example.test/ping")

    def failing(*args, **kwargs):
        raise telemetry_service.urllib.error.URLError("offline")

    monkeypatch.setattr(telemetry_service.urllib.request, "urlopen", failing)
    assert telemetry_service.get_public_stats() is None

    telemetry_service._about_cache.update(fetched_at=0.0, ttl=0, data=None)
    monkeypatch.setattr(
        telemetry_service.urllib.request, "urlopen", lambda *a, **k: FakeJsonResponse({"unexpected": 1})
    )
    assert telemetry_service.get_public_stats() is None


def test_about_stats_endpoint(monkeypatch, clean_about_cache):
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    monkeypatch.setattr("routes.system.get_public_stats", lambda: None)
    assert client.get("/system/about-stats").json() == {
        "available": False,
        "active_installations": None,
        "active_window_days": None,
        "countries": [],
        "versions": [],
        "channels": [],
    }

    monkeypatch.setattr("routes.system.get_public_stats", lambda: PUBLIC_STATS)
    body = client.get("/system/about-stats").json()
    assert body["available"] is True
    assert body["active_installations"] == 12
    assert body["channels"][1] == {"channel": "dev", "n": 1}
    assert body["countries"][0] == {"country": "IT", "n": 9}


def test_channel_defaults_and_validation(monkeypatch):
    monkeypatch.delenv("IMAGE_CHANNEL", raising=False)
    assert telemetry_service._channel() == "unknown"
    monkeypatch.setenv("IMAGE_CHANNEL", "DEV")
    assert telemetry_service._channel() == "dev"
    monkeypatch.setenv("IMAGE_CHANNEL", "qualcosa")
    assert telemetry_service._channel() == "unknown"
