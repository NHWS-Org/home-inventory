import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.mark.parametrize("legacy_schema", [False, True])
@pytest.mark.parametrize("starting_revision", [None, "d6e7f8a9b0c1", "c4d5e6f7a8b9"])
def test_sqlite_bootstrap_and_migrations(tmp_path, legacy_schema, starting_revision):
    database_url = f"sqlite:///{tmp_path / 'inventory.db'}"
    if legacy_schema:
        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE inventories (id INTEGER PRIMARY KEY, name TEXT, "
                "owner_id INTEGER, data_ins DATETIME, data_mod DATETIME, "
                "user_ins INTEGER, user_mod INTEGER, type VARCHAR(16))"
            ))
        engine.dispose()

    script = (
        "from database import init_db; "
        "from alembic import command; "
        "from alembic.config import Config; "
        "init_db(); "
        "command.upgrade(Config('alembic.ini'), 'head')"
    )
    if starting_revision:
        result = subprocess.run(
            [sys.executable, "-c",
             "from database import init_db; from alembic import command; "
             "from alembic.config import Config; init_db(); "
             f"command.upgrade(Config('alembic.ini'), '{starting_revision}')"],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "DATABASE_TYPE": "SQLITE", "DATABASE_URL": database_url},
            check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    for _ in range(2):
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env={
                **os.environ,
                "DATABASE_TYPE": "SQLITE",
                "DATABASE_URL": database_url,
            },
            check=True,
            capture_output=True,
            text=True,
        )

    engine = create_engine(database_url)
    with engine.connect() as connection:
        columns = {column["name"]: column for column in inspect(connection).get_columns("inventories")}
        assert columns["type"]["nullable"] is False
        tables = inspect(connection).get_table_names()
        assert {
            "security_audit", "notification_events", "notification_preferences",
            "push_subscriptions", "push_deliveries",
        }.issubset(tables)
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "b0c1d2e3f4a5"
        assert "notification_rules" not in tables
    engine.dispose()
