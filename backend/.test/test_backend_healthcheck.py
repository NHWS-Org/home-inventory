from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dependencies import init_roles_and_admin
from models import Base


def test_image_healthcheck_uses_short_interval_and_startup_grace():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "HEALTHCHECK --interval=5s --timeout=5s --start-period=60s --retries=3" in dockerfile
    assert "http://localhost:8000/system/health-check" in dockerfile


def test_fresh_database_requires_initial_admin_password(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            with pytest.raises(RuntimeError, match="ADMIN_PASSWORD must be configured"):
                init_roles_and_admin(db)
    finally:
        engine.dispose()
