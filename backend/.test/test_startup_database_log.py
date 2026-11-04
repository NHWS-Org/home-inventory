from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("database_type", "database_url", "expected_url"),
    [
        (
            "POSTGRES",
            "postgresql+psycopg://admin:secret-password@db:5432/inventory"
            "?password=query-secret",
            "postgresql+psycopg://admin:***@db:5432/inventory",
        ),
        (
            "MYSQL",
            "mysql+pymysql://admin:secret-password@mysql:3306/inventory"
            "?token=query-secret",
            "mysql+pymysql://admin:***@mysql:3306/inventory",
        ),
        (
            "SQLITE",
            "sqlite:////app/data/inventory.db",
            "sqlite:////app/data/inventory.db",
        ),
    ],
)
def test_startup_logs_database_without_secrets(database_type, database_url, expected_url):
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()
    startup_code = entrypoint.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    stub = f"""
import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from sqlalchemy.engine import make_url

database = ModuleType("database")
database.DATABASE_TYPE = {database_type!r}
database.engine = SimpleNamespace(
    url=make_url({database_url!r}), connect=nullcontext,
)
database.init_db = lambda: None
sys.modules["database"] = database
"""
    result = subprocess.run(
        [sys.executable, "-u", "-"],
        input=stub + startup_code,
        capture_output=True,
        text=True,
        check=True,
    )
    assert f"Database configured: {database_type} ({expected_url})" in result.stdout
    assert result.stdout.index("Database configured:") < result.stdout.index("Bootstrapping")
    for secret in ("secret-password", "query-secret", "?password=", "?token="):
        assert secret not in result.stdout + result.stderr
