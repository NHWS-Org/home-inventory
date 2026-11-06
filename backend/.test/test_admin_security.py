from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import create_engine, select, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth_config
from dependencies import get_db, get_current_user
from models import Base, DeviceSession, Role, SecurityAudit, User
from routes.admin import router as admin_router
from routes.auth import router as auth_router, hash_password, ALGORITHM

PASSWORD = "test-admin-password"


@pytest.fixture
def security(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "AUTO")
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)
    monkeypatch.setattr(auth_config, "__file__", str(tmp_path / "auth_config.py"))
    auth_config.get_secret_key.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([Role(id=1, name="admin"), Role(id=2, name="viewer")])
        db.flush()
        db.add_all([
            User(id=1, username="admin", hashed_password=hash_password(PASSWORD), role_id=1),
            User(id=2, username="viewer", hashed_password=hash_password(PASSWORD), role_id=2),
            User(id=3, username="blocked", hashed_password=hash_password(PASSWORD), role_id=1, is_blocked=True),
        ])
    app = FastAPI()
    app.include_router(auth_router, prefix="/auth")
    app.include_router(admin_router, prefix="/admin")

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database

    @app.get("/protected")
    def protected(user=Depends(get_current_user)):
        return {"username": user.username}

    yield factory, TestClient(app), tmp_path
    auth_config.get_secret_key.cache_clear()
    engine.dispose()


def login(client, username="admin"):
    response = client.post("/auth/login", data={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("endpoint", ["revoke-sessions", "rotate-key"])
def test_admin_password_and_confirmation_required(security, endpoint):
    factory, client, _ = security
    admin = login(client)
    viewer = login(client, "viewer")
    path = f"/admin/security/{endpoint}"
    assert client.post(path, json={"password": PASSWORD, "confirm": True}).status_code == 401
    assert client.post(path, headers=bearer(viewer), json={
        "password": PASSWORD, "confirm": True,
    }).status_code == 403
    for payload in [
        {"password": PASSWORD}, {"password": PASSWORD, "confirm": False},
        {"password": "", "confirm": True}, {"password": PASSWORD, "confirm": True, "extra": 1},
    ]:
        assert client.post(path, headers=bearer(admin), json=payload).status_code == 422
    response = client.post(path, headers=bearer(admin), json={"password": "wrong", "confirm": True})
    assert response.status_code == 403
    assert client.get("/protected", headers=bearer(admin)).status_code == 200
    with factory() as db:
        assert db.scalars(select(SecurityAudit)).one().outcome == "password_rejected"
        assert all(session.revoked_at is None for session in db.scalars(select(DeviceSession)))


def test_global_revocation_covers_other_users_and_legacy_tokens(security):
    factory, client, _ = security
    admin, viewer = login(client), login(client, "viewer")
    key = auth_config.current_secret_key()
    legacy = jwt.encode({
        "sub": "viewer", "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }, key, algorithm=ALGORITHM)
    legacy_with_iat = jwt.encode({
        "sub": "viewer", "iat": datetime.now(timezone.utc).timestamp(),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }, key, algorithm=ALGORITHM)
    assert client.get("/protected", headers=bearer(legacy)).status_code == 200
    response = client.post("/admin/security/revoke-sessions", headers=bearer(admin), json={
        "password": PASSWORD, "confirm": True,
    })
    assert response.status_code == 200, response.text
    assert auth_config.current_secret_key() == key
    # Simulate databases whose DATETIME fields discard fractional seconds.
    with factory.begin() as db:
        entry = db.scalars(select(SecurityAudit)).one()
        entry.created_at = entry.created_at.replace(microsecond=0)
    for token in (admin, viewer, legacy, legacy_with_iat):
        assert client.get("/protected", headers=bearer(token)).status_code == 401
        assert client.get("/auth/me", headers=bearer(token)).status_code == 401
    assert client.get("/protected", headers=bearer(login(client))).status_code == 200
    with factory() as db:
        entry = db.scalars(select(SecurityAudit)).one()
        assert entry.action == "revoke_sessions" and entry.outcome == "succeeded"
        assert entry.sessions_revoked == 2 and entry.actor_username == "admin"


def test_auto_rotation_is_immediate_persistent_and_audited(security, caplog):
    factory, client, _ = security
    assert client.get("/auth/me").status_code == 200
    admin, viewer = login(client), login(client, "viewer")
    before = auth_config.current_secret_key()
    assert client.get("/admin/security", headers=bearer(admin)).json()["can_rotate"]
    response = client.post("/admin/security/rotate-key", headers=bearer(admin), json={
        "password": PASSWORD, "confirm": True,
    })
    assert response.status_code == 200, response.text
    after = auth_config.current_secret_key()
    assert before != after
    auth_config.get_secret_key.cache_clear()
    assert auth_config.current_secret_key() == after
    for token in (admin, viewer):
        assert client.get("/protected", headers=bearer(token)).status_code == 401
        assert client.get("/auth/me", headers=bearer(token)).status_code == 401
    fresh = login(client)
    audit = client.get("/admin/security/audit", headers=bearer(fresh)).json()
    assert audit[0]["action"] == "rotate_key" and audit[0]["outcome"] == "succeeded"
    assert "password" not in str(audit)
    assert before not in caplog.text and after not in caplog.text and PASSWORD not in caplog.text
    with factory() as db:
        assert all(session.revoked_at is not None for session in db.scalars(
            select(DeviceSession).where(DeviceSession.id <= 2),
        ))


@pytest.mark.parametrize("mode", ["environment", "file"])
def test_external_rotation_blocked_but_revocation_allowed(security, monkeypatch, mode):
    factory, client, directory = security
    if mode == "environment":
        monkeypatch.setenv("SECRET_KEY", "e" * 64)
    else:
        path = directory / "mounted.key"
        path.write_text("f" * 64)
        monkeypatch.setenv("SECRET_KEY_FILE", str(path))
    auth_config.get_secret_key.cache_clear()
    admin = login(client)
    old = auth_config.current_secret_key()
    state = client.get("/admin/security", headers=bearer(admin)).json()
    assert not state["can_rotate"]
    assert state["rotation_message"] == "Rotazione gestita tramite configurazione dell'installazione"
    response = client.post("/admin/security/rotate-key", headers=bearer(admin), json={
        "password": PASSWORD, "confirm": True,
    })
    assert response.status_code == 409
    assert response.json()["detail"] == state["rotation_message"]
    assert auth_config.current_secret_key() == old
    assert client.get("/protected", headers=bearer(admin)).status_code == 200
    with factory() as db:
        assert db.scalars(select(SecurityAudit)).one().outcome == "blocked_external"
    assert client.post("/admin/security/revoke-sessions", headers=bearer(admin), json={
        "password": PASSWORD, "confirm": True,
    }).status_code == 200


def test_failed_rotation_audited_and_fails_closed(security, monkeypatch):
    from routes import admin as module

    factory, client, _ = security
    token = login(client)
    old = auth_config.current_secret_key()

    def failing_rotation():
        raise OSError("private secret content")

    monkeypatch.setattr(module, "rotate_automatic_key", failing_rotation)
    response = client.post("/admin/security/rotate-key", headers=bearer(token), json={
        "password": PASSWORD, "confirm": True,
    })
    assert response.status_code == 500
    assert "private" not in response.text
    assert auth_config.current_secret_key() == old
    assert client.get("/protected", headers=bearer(token)).status_code == 401
    assert client.get("/protected", headers=bearer(login(client))).status_code == 200
    with factory() as db:
        assert db.scalars(select(SecurityAudit)).one().outcome == "rotation_failed"


def test_blocked_admin_and_viewer_cannot_access_security(security):
    _, client, _ = security
    viewer = login(client, "viewer")
    for path in ("/admin/security", "/admin/security/audit"):
        assert client.get(path, headers=bearer(viewer)).status_code == 403
    assert client.post("/auth/login", data={"username": "blocked", "password": PASSWORD}).status_code == 403


def test_password_confirmation_attempts_are_bounded_and_audited(security):
    factory, client, _ = security
    admin = login(client)
    for _ in range(5):
        assert client.post("/admin/security/revoke-sessions", headers=bearer(admin), json={
            "password": "wrong", "confirm": True,
        }).status_code == 403
    response = client.post("/admin/security/rotate-key", headers=bearer(admin), json={
        "password": PASSWORD, "confirm": True,
    })
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "300"
    with factory() as db:
        rows = db.scalars(select(SecurityAudit).order_by(SecurityAudit.id)).all()
        assert len(rows) == 6 and rows[-1].outcome == "rate_limited"
        for row in rows:
            row.created_at -= timedelta(minutes=6)
        db.commit()
    assert client.post("/admin/security/revoke-sessions", headers=bearer(admin), json={
        "password": PASSWORD, "confirm": True,
    }).status_code == 200


def test_token_timestamp_is_created_after_waiting_for_rotation(security, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Event
    from routes import auth

    waiting = Event()
    original_lock = auth.key_lock
    auth_config.current_secret_key()

    @contextmanager
    def observed_lock():
        waiting.set()
        with original_lock():
            yield

    monkeypatch.setattr(auth, "key_lock", observed_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with original_lock(exclusive=True):
            task = pool.submit(auth.create_access_token, {"sub": "admin"})
            assert waiting.wait(timeout=5)
            auth_config.rotate_automatic_key()
            cutoff = datetime.now(timezone.utc).timestamp()
        token = task.result(timeout=5)
    payload = jwt.decode(token, auth_config.current_secret_key(), algorithms=[ALGORITHM])
    assert payload["iat"] > cutoff


def test_login_does_not_decode_token_with_a_potentially_changed_key(security, monkeypatch):
    _, client, _ = security

    def unexpected_decode(*args, **kwargs):
        raise AssertionError("Login must not decode its freshly signed token")

    monkeypatch.setattr(jwt, "decode", unexpected_decode)
    login(client)


@pytest.mark.parametrize("endpoint", ["sessions", "logout"])
def test_rotation_during_session_endpoint_returns_401_not_500(security, monkeypatch, endpoint):
    from routes import auth

    _, client, _ = security
    token = login(client)
    original_decode = auth.decode_access_token

    def rotate_then_decode(value):
        with auth_config.key_lock(exclusive=True):
            auth_config.rotate_automatic_key()
        return original_decode(value)

    monkeypatch.setattr(auth, "decode_access_token", rotate_then_decode)
    response = client.request("GET" if endpoint == "sessions" else "POST",
                              f"/auth/{endpoint}", headers=bearer(token))
    assert response.status_code == 401


@pytest.mark.parametrize("failing_commit", [1, 2])
def test_audit_commit_failures_report_persisted_state(security, monkeypatch, failing_commit):
    from sqlalchemy.exc import OperationalError

    factory, client, _ = security
    token = login(client)
    old_key = auth_config.current_secret_key()
    original_commit = factory.class_.commit
    commits = 0

    def commit(db):
        nonlocal commits
        commits += 1
        if commits == failing_commit:
            raise OperationalError("private database detail", {}, Exception())
        original_commit(db)

    monkeypatch.setattr(factory.class_, "commit", commit)
    response = client.post("/admin/security/rotate-key", headers=bearer(token), json={
        "password": PASSWORD, "confirm": True,
    })
    assert response.status_code == 500
    assert "private" not in response.text
    with factory() as db:
        audits = db.scalars(select(SecurityAudit)).all()
        session = db.scalars(select(DeviceSession)).one()
        if failing_commit == 1:
            assert audits == [] and session.revoked_at is None
            assert auth_config.current_secret_key() == old_key
            assert "annullata" in response.json()["detail"]
        else:
            assert len(audits) == 1 and audits[0].outcome == "pending"
            assert session.revoked_at is not None
            assert auth_config.current_secret_key() != old_key
            assert "non confermato" in response.json()["detail"]
    expected_status = 200 if failing_commit == 1 else 401
    assert client.get("/protected", headers=bearer(token)).status_code == expected_status


def test_already_running_process_observes_rotation_without_restart(security):
    import os
    import subprocess
    import sys

    _, client, directory = security
    token = login(client)
    script = (
        "import sys; from pathlib import Path; import auth_config; "
        "auth_config.__file__ = str(Path(sys.argv[1]) / 'auth_config.py'); "
        "before = auth_config.current_secret_key(); print('ready', flush=True); "
        "sys.stdin.readline(); "
        "assert before != auth_config.current_secret_key(); print('updated', flush=True)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(directory)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "SECRET_KEY": "AUTO", "SECRET_KEY_FILE": ""},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        assert client.post("/admin/security/rotate-key", headers=bearer(token), json={
            "password": PASSWORD, "confirm": True,
        }).status_code == 200
        out, err = process.communicate("\n", timeout=15)
        assert process.returncode == 0, err
        assert out.strip() == "updated"
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)


@pytest.mark.parametrize("bootstrap", [False, True])
def test_security_audit_migration_upgrade_and_downgrade(tmp_path, bootstrap):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    path = Path(__file__).resolve().parents[1] / "migrations/versions/d6e7f8a9b0c1_security_audit.py"
    spec = importlib.util.spec_from_file_location("security_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if bootstrap:
        Base.metadata.create_all(engine)
    else:
        Base.metadata.tables["roles"].create(engine)
        Base.metadata.tables["users"].create(engine)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()
            assert inspect(connection).has_table("security_audit")
            module.downgrade()
            assert not inspect(connection).has_table("security_audit")
            assert inspect(connection).has_table("users")
    engine.dispose()
