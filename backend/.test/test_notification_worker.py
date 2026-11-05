import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base
import notification_worker as worker


@pytest.fixture
def health(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    path = tmp_path / "heartbeat.json"
    yield factory, path
    engine.dispose()


def test_healthcheck_requires_heartbeat_and_database(health):
    factory, path = health
    assert not worker.check_health(factory, path)
    worker.write_heartbeat(path)
    assert worker.check_health(factory, path)
    assert not path.with_suffix(".tmp").exists()
    with factory() as db:
        db.connection().exec_driver_sql("DROP TABLE notification_events")
        db.commit()
    assert not worker.check_health(factory, path)


@pytest.mark.parametrize("heartbeat", [
    {"pid": os.getpid(), "updated_at": time.monotonic() - worker.HEARTBEAT_MAX_AGE_SECONDS - 1},
    {"pid": os.getpid(), "updated_at": time.monotonic() + 100},
    {"pid": -1, "updated_at": time.monotonic()},
    {"pid": "1", "updated_at": time.monotonic()},
    {"pid": os.getpid(), "updated_at": "bad"},
    [],
    {},
])
def test_healthcheck_rejects_stale_or_invalid_heartbeat(health, heartbeat):
    factory, path = health
    path.write_text(json.dumps(heartbeat))
    assert not worker.check_health(factory, path)


def test_healthcheck_rejects_dead_process(health, monkeypatch):
    factory, path = health
    worker.write_heartbeat(path)

    def dead_process(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(worker.os, "kill", dead_process)
    assert not worker.check_health(factory, path)


def test_healthcheck_does_not_log_private_exception_content(health, caplog):
    _, path = health
    worker.write_heartbeat(path)

    def unavailable():
        raise worker.SQLAlchemyError("private database connection details")

    assert not worker.check_health(unavailable, path)
    assert "private database" not in caplog.text
    assert "SQLAlchemyError" in caplog.text


def test_running_worker_cli_healthcheck_and_clean_shutdown(tmp_path):
    database = tmp_path / "worker.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()
    environment = {
        **os.environ, "DATABASE_TYPE": "SQLITE", "DATABASE_URL": f"sqlite:///{database}",
        "TMPDIR": str(tmp_path),
    }
    directory = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "notification_worker"]
    path = tmp_path / worker.HEARTBEAT_PATH.name
    process = subprocess.Popen(
        command, cwd=directory, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not path.exists():
            assert process.poll() is None, process.communicate()
            assert time.monotonic() < deadline, "Worker did not publish heartbeat"
            time.sleep(0.05)
        result = subprocess.run(
            [*command, "--healthcheck"], cwd=directory, env=environment,
            capture_output=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr.decode()
    finally:
        process.terminate()
        process.communicate(timeout=10)
    assert process.returncode == 0
    assert not path.exists()
    result = subprocess.run(
        [*command, "--healthcheck"], cwd=directory, env=environment,
        capture_output=True, timeout=10,
    )
    assert result.returncode == 1
