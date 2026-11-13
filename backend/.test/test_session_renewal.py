from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth_config import ALGORITHM, current_secret_key
from dependencies import get_current_user, get_db
from models import Base, DeviceSession, PushSubscription, Role, User
import routes.auth as auth
from web_push import endpoint_hash

ENDPOINT = "https://fcm.googleapis.com/fcm/send/renewal-test"


@pytest.fixture
def renewal(monkeypatch):
    monkeypatch.setattr(auth, "ACCESS_TOKEN_EXPIRE_MINUTES", 30)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with factory.begin() as db:
        db.add(Role(id=1, name="admin"))
        db.flush()
        db.add(User(id=1, username="alice", role_id=1))
        db.flush()
        db.add(DeviceSession(id=1, user_id=1, session_token_id="session", expires_at=now + timedelta(minutes=14)))
        db.flush()
        db.add(PushSubscription(
            id=1, user_id=1, session_id=1, endpoint=ENDPOINT, endpoint_hash=endpoint_hash(ENDPOINT),
            p256dh="test", auth="test", generation="generation", vapid_fingerprint="fingerprint",
            created_at=now, updated_at=now, expires_at=now + timedelta(minutes=14),
        ))
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database

    @app.get("/protected")
    def protected(user=Depends(get_current_user)):
        return {"username": user.username}

    yield factory, TestClient(app)
    engine.dispose()


def token(remaining=14, **claims):
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": "alice", "jti": "session", "iat": (now - timedelta(minutes=30 - remaining)).timestamp(),
        "exp": now + timedelta(minutes=remaining), **claims,
    }, current_secret_key(), algorithm=ALGORITHM)


def headers(value):
    return {"Authorization": f"Bearer {value}"}


def test_renewal_occurs_only_below_half_and_preserves_session_and_push(renewal):
    factory, client = renewal
    with factory.begin() as db:
        db.get(DeviceSession, 1).expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=20)
    fresh = token(remaining=16)
    response = client.post("/auth/renew", headers=headers(fresh), json={})
    assert response.status_code == 200
    assert response.json() == {"access_token": fresh, "renewed": False, "push_extended": None}
    old = token()
    response = client.post("/auth/renew", headers=headers(old), json={
        "push": {"id": 1, "endpoint": ENDPOINT, "expiration_time": None},
    })
    assert response.status_code == 200, response.text
    assert response.json()["renewed"] is True
    assert response.json()["push_extended"] is True
    new = response.json()["access_token"]
    decoded = jwt.decode(new, current_secret_key(), algorithms=[ALGORITHM])
    assert decoded["jti"] == "session"
    assert decoded["exp"] - datetime.now(timezone.utc).timestamp() > 29 * 60
    assert client.get("/protected", headers=headers(new)).status_code == 200
    with factory() as db:
        session = db.get(DeviceSession, 1)
        subscription = db.get(PushSubscription, 1)
        assert session.expires_at > datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=29)
        assert subscription.expires_at == session.expires_at
        assert subscription.generation == "generation"
        assert len(db.scalars(select(DeviceSession)).all()) == 1


@pytest.mark.parametrize(("seconds_remaining", "expected"), [(901, False), (900, False), (899, True)])
def test_exact_half_lifetime_boundary(renewal, monkeypatch, seconds_remaining, expected):
    _, client = renewal
    fixed = datetime.now(timezone.utc).replace(microsecond=0)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is not None else fixed.replace(tzinfo=None)

    monkeypatch.setattr(auth, "datetime", SimpleNamespace(
        datetime=FrozenDateTime, timedelta=timedelta, timezone=timezone,
    ))
    value = jwt.encode({
        "sub": "alice", "jti": "session", "iat": (fixed - timedelta(minutes=15)).timestamp(),
        "exp": int(fixed.timestamp()) + seconds_remaining,
    }, current_secret_key(), algorithm=ALGORITHM)
    response = client.post("/auth/renew", headers=headers(value), json={})
    assert response.status_code == 200
    assert response.json()["renewed"] is expected


def test_native_expiration_is_not_extended(renewal):
    factory, client = renewal
    native = datetime.now(timezone.utc) + timedelta(minutes=18)
    response = client.post("/auth/renew", headers=headers(token()), json={
        "push": {"id": 1, "endpoint": ENDPOINT, "expiration_time": int(native.timestamp() * 1000)},
    })
    assert response.json()["push_extended"] is True
    with factory() as db:
        assert db.get(PushSubscription, 1).expires_at == native.replace(tzinfo=None, microsecond=(native.microsecond // 1000) * 1000)
        assert db.get(DeviceSession, 1).expires_at > db.get(PushSubscription, 1).expires_at


@pytest.mark.parametrize("push", [
    {"id": 99, "endpoint": ENDPOINT, "expiration_time": None},
    {"id": 1, "endpoint": "https://fcm.googleapis.com/fcm/send/other", "expiration_time": None},
    {"id": 1, "endpoint": ENDPOINT, "expiration_time": 1},
])
def test_missing_mismatched_or_expired_browser_subscription_not_extended(renewal, push):
    factory, client = renewal
    with factory() as db:
        original = db.get(PushSubscription, 1).expires_at
    response = client.post("/auth/renew", headers=headers(token()), json={"push": push})
    assert response.status_code == 200
    assert response.json()["push_extended"] is False
    with factory() as db:
        assert db.get(PushSubscription, 1).expires_at == original


@pytest.mark.parametrize("condition", ["revoked", "expired", "blocked", "legacy", "expired_token", "cutoff"])
def test_revoked_expired_blocked_or_legacy_token_cannot_renew(renewal, condition):
    factory, client = renewal
    current = token()
    with factory.begin() as db:
        if condition == "revoked":
            db.get(DeviceSession, 1).revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif condition == "expired":
            db.get(DeviceSession, 1).expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        elif condition == "blocked":
            db.get(User, 1).is_blocked = True
        elif condition == "legacy":
            current = token(jti=None)
        elif condition == "expired_token":
            current = token(remaining=-1)
        elif condition == "cutoff":
            db.get(User, 1).auth_revoked_before = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    assert client.post("/auth/renew", headers=headers(current), json={}).status_code in (401, 403)


def test_commit_failure_does_not_extend_session_or_push(renewal):
    factory, client = renewal
    with factory() as db:
        previous = db.get(DeviceSession, 1).expires_at

    def fail_push(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("UPDATE PUSH_SUBSCRIPTIONS"):
            raise OperationalError(statement, {}, RuntimeError("simulated failure"))

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", fail_push)
    try:
        with pytest.raises(OperationalError):
            client.post("/auth/renew", headers=headers(token()), json={
                "push": {"id": 1, "endpoint": ENDPOINT, "expiration_time": None},
            })
    finally:
        event.remove(engine, "before_cursor_execute", fail_push)
    with factory() as db:
        assert db.get(DeviceSession, 1).expires_at == previous


def test_concurrent_renewals_keep_same_session_and_subscription(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "ACCESS_TOKEN_EXPIRE_MINUTES", 30)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'renewal-race.db'}", connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with factory.begin() as db:
        db.add(Role(id=1, name="admin"))
        db.flush()
        db.add(User(id=1, username="alice", role_id=1))
        db.flush()
        db.add(DeviceSession(id=1, user_id=1, session_token_id="session", expires_at=now + timedelta(minutes=14)))
        db.flush()
        db.add(PushSubscription(
            id=1, user_id=1, session_id=1, endpoint=ENDPOINT, endpoint_hash=endpoint_hash(ENDPOINT),
            p256dh="test", auth="test", generation="generation", vapid_fingerprint="fingerprint",
            created_at=now, updated_at=now, expires_at=now + timedelta(minutes=14),
        ))
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    old = token()
    body = {"push": {"id": 1, "endpoint": ENDPOINT, "expiration_time": None}}
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                lambda _: client.post("/auth/renew", headers=headers(old), json=body), range(2),
            ))
        assert all(result.status_code == 200 and result.json()["push_extended"] for result in results)
        with factory() as db:
            assert len(db.scalars(select(DeviceSession)).all()) == 1
            assert db.get(PushSubscription, 1).generation == "generation"
            assert db.get(DeviceSession, 1).expires_at > now + timedelta(minutes=29)
            assert db.get(PushSubscription, 1).expires_at > now + timedelta(minutes=29)
    finally:
        engine.dispose()
