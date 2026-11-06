import os
from pathlib import Path
import subprocess
import sys

from app_version import API_VERSION
from main import app
from routes.system import get_api_version, get_health


def test_version_shared_by_openapi_and_system_endpoints(monkeypatch):
    monkeypatch.setenv("API_VERSION", "not-the-release")
    assert API_VERSION == Path(__file__).resolve().parents[1].joinpath("VERSION").read_text().strip()
    assert app.version == app.openapi()["info"]["version"] == API_VERSION
    assert get_api_version() == {"version": API_VERSION}
    assert get_health()["version"] == API_VERSION


def test_version_independent_of_cwd_and_environment(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "from app_version import API_VERSION; print(API_VERSION)"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(backend), "API_VERSION": "obsolete"},
        capture_output=True, text=True, timeout=15, check=True,
    )
    assert result.stdout.strip() == API_VERSION


def test_version_not_in_image_or_example_environment():
    backend = Path(__file__).resolve().parents[1]
    assert "API_VERSION=" not in (backend / ".env.example").read_text()
    assert "API_VERSION=" not in (backend / "Dockerfile").read_text()
