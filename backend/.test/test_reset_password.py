from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os
import select as io_select
import subprocess
import sys
from threading import Event
import time

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth_config
from dependencies import get_current_user, get_db
from models import Base, DeviceSession, Role, User
import reset_password
import routes.auth
from routes.auth import create_access_token, hash_password, router, verify_password


@pytest.fixture
def recovery(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(Role(id=1, name="admin"))
        db.flush()
        db.add_all([
            User(id=1, username="alice", hashed_password=hash_password("old-password"), role_id=1),
            User(id=2, username="bob", hashed_password=hash_password("old-password"), role_id=1),
        ])
    monkeypatch.setattr(reset_password, "SessionLocal", factory)
    app = FastAPI()
    app.include_router(router, prefix="/auth")

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database

    @app.get("/protected")
    def protected(user=Depends(get_current_user)):
        return {"username": user.username}

    yield factory, TestClient(app)
    engine.dispose()


def login(client, username, password):
    return client.post("/auth/login", data={"username": username, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_reset_revokes_all_target_tokens_but_not_other_users(recovery):
    factory, client = recovery
    alice = login(client, "alice", "old-password").json()["access_token"]
    alice_other = login(client, "alice", "old-password").json()["access_token"]
    bob = login(client, "bob", "old-password").json()["access_token"]
    legacy = create_access_token({"sub": "alice"})
    no_iat = jwt.encode({
        "sub": "alice", "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }, auth_config.current_secret_key(), algorithm=auth_config.ALGORITHM)

    assert reset_password.reset_password("alice", "new-password") == 2
    for token in (alice, alice_other, legacy, no_iat):
        assert client.get("/protected", headers=bearer(token)).status_code == 401
    assert client.get("/protected", headers=bearer(bob)).status_code == 200
    assert login(client, "alice", "old-password").status_code == 401
    new_token = login(client, "alice", "new-password").json()["access_token"]
    assert client.get("/protected", headers=bearer(new_token)).status_code == 200
    with factory() as db:
        sessions = db.scalars(select(DeviceSession).where(DeviceSession.user_id == 1)).all()
        assert sum(session.revoked_at is not None for session in sessions) == 2


def test_invalid_reset_does_not_change_password_or_sessions(recovery):
    _, client = recovery
    token = login(client, "alice", "old-password").json()["access_token"]
    for username, password in [("missing", "new-password"), ("alice", ""), ("alice", "x" * 73)]:
        with pytest.raises(ValueError):
            reset_password.reset_password(username, password)
    assert client.get("/protected", headers=bearer(token)).status_code == 200
    assert login(client, "alice", "old-password").status_code == 200


def test_reset_rolls_back_password_and_cutoff_when_session_revocation_fails(recovery):
    factory, client = recovery
    token = login(client, "alice", "old-password").json()["access_token"]
    engine = factory.kw["bind"]

    def fail_revocation(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("UPDATE DEVICE_SESSIONS"):
            raise OperationalError(statement, {}, RuntimeError("simulated failure"))

    event.listen(engine, "before_cursor_execute", fail_revocation)
    try:
        with pytest.raises(OperationalError):
            reset_password.reset_password("alice", "new-password")
    finally:
        event.remove(engine, "before_cursor_execute", fail_revocation)
    assert client.get("/protected", headers=bearer(token)).status_code == 200
    assert login(client, "alice", "old-password").status_code == 200
    assert login(client, "alice", "new-password").status_code == 401
    with factory() as db:
        assert db.scalar(select(User).where(User.username == "alice")).auth_revoked_before is None


def test_reset_prevents_concurrent_login_with_old_password(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(Role(id=1, name="admin"))
        db.flush()
        db.add(User(username="alice", hashed_password=hash_password("old-password"), role_id=1))
    monkeypatch.setattr(reset_password, "SessionLocal", factory)
    monkeypatch.setenv("SECRET_KEY", "test-key-for-password-recovery-32-bytes")
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)
    auth_config.get_secret_key.cache_clear()
    verified, resume = Event(), Event()
    original_verify = routes.auth.verify_password

    def delayed_verify(password, password_hash):
        result = original_verify(password, password_hash)
        verified.set()
        assert resume.wait(10)
        return result

    monkeypatch.setattr(routes.auth, "verify_password", delayed_verify)
    app = FastAPI()
    app.include_router(router, prefix="/auth")

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(login, client, "alice", "old-password")
            try:
                assert verified.wait(10)
                assert reset_password.reset_password("alice", "new-password") == 0
            finally:
                resume.set()
            assert pending.result(timeout=10).status_code == 401
        with factory() as db:
            assert db.scalars(select(DeviceSession)).all() == []
    finally:
        auth_config.get_secret_key.cache_clear()
        engine.dispose()


def test_cli_requires_tty_and_never_accepts_password_argument(recovery, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["reset_password", "alice"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert reset_password.main() == 1
    assert "terminale interattivo" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["reset_password", "alice", "password"])
    with pytest.raises(SystemExit) as exc:
        reset_password.main()
    assert exc.value.code == 2


def test_cli_confirmation_mismatch_preserves_password(recovery, monkeypatch, capsys):
    _, client = recovery
    monkeypatch.setattr(sys, "argv", ["reset_password", "alice"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    answers = iter(["secret-one", "secret-two"])
    monkeypatch.setattr(reset_password.getpass, "getpass", lambda _: next(answers))
    assert reset_password.main() == 1
    output = capsys.readouterr()
    assert "non coincidono" in output.err
    assert "secret-one" not in output.err
    assert login(client, "alice", "old-password").status_code == 200


@pytest.mark.skipif(sys.platform == "win32", reason="Requires a Unix pseudo-terminal")
def test_real_cli_prompts_without_echo_and_persists(tmp_path):
    import pty

    database = tmp_path / "recovery.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(Role(id=1, name="admin"))
        db.flush()
        db.add(User(username="alice", hashed_password=hash_password("old-password"), role_id=1))
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database}"
    env["DATABASE_TYPE"] = "SQLITE"
    env["SECRET_KEY"] = "test-key-for-password-recovery-32-bytes"
    env.pop("SECRET_KEY_FILE", None)
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "reset_password", "alice"],
        cwd=Path(__file__).parents[1], env=env, stdin=slave, stdout=slave, stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    output = bytearray()

    def wait_for(text):
        deadline = time.monotonic() + 15
        while text not in output and time.monotonic() < deadline:
            if io_select.select([master], [], [], 1)[0]:
                output.extend(os.read(master, 4096))
        assert text in output

    try:
        wait_for(b"Nuova password: ")
        os.write(master, b"private-test-password\n")
        wait_for(b"Ripeti password: ")
        os.write(master, b"private-test-password\n")
        wait_for(b"Password aggiornata.")
        assert process.wait(timeout=15) == 0
        assert b"private-test-password" not in output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
    with factory() as db:
        user = db.scalar(select(User).where(User.username == "alice"))
        assert verify_password("private-test-password", user.hashed_password)
        assert user.auth_revoked_before is not None
    engine.dispose()


def test_migration_adds_and_removes_user_cutoff():
    path = Path(__file__).parents[1] / "migrations/versions/b0c1d2e3f4a5_user_token_revocation.py"
    spec = importlib.util.spec_from_file_location("user_cutoff_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        assert "auth_revoked_before" in {col["name"] for col in inspect(connection).get_columns("users")}
        migration.downgrade()
        assert "auth_revoked_before" not in {col["name"] for col in inspect(connection).get_columns("users")}
    engine.dispose()
