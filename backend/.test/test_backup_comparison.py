import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, String, Table, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backup_archive import create_backup_archive, read_backup_archive, write_backup_archive
from backup_comparison import REDACTED, compare_snapshots
from dependencies import get_current_user, get_db
from models import Base
from routes import backup


@pytest.fixture
def comparison_context(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    versions = Table(
        "alembic_version", MetaData(),
        Column("version_num", String(32), primary_key=True),
    )
    versions.create(engine)
    with engine.begin() as connection:
        connection.execute(versions.insert().values(version_num="8a9b0c1d2e3f"))
        connection.execute(Base.metadata.tables["roles"].insert().values(id=1, name="admin"))
        connection.execute(Base.metadata.tables["users"].insert().values(
            id=1, username="admin", hashed_password="private-hash", role_id=1,
        ))
        connection.execute(Base.metadata.tables["inventories"].insert().values(
            id=1, name="Casa", type="INVENTORY", owner_id=1,
        ))
        connection.execute(Base.metadata.tables["items"].insert().values(
            id=1, name="Pasta", quantity=2, inventory_id=1,
        ))

    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)
    app = FastAPI()
    app.include_router(backup.router, prefix="/backup")
    role = SimpleNamespace(name="admin")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role)

    def override_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with Session(engine) as db:
        metadata = {
            "format": backup.BACKUP_FORMAT,
            "format_version": backup.BACKUP_FORMAT_VERSION,
            "db_alembic_version": "8a9b0c1d2e3f",
        }
        create_backup_archive(db, tmp_path / "before.hibackup", metadata)
    yield TestClient(app), engine, tmp_path, role
    engine.dispose()


def test_identical_current_database_includes_empty_tables_and_does_not_write(comparison_context):
    client, engine, path, _role = comparison_context
    with Session(engine) as db:
        before = backup.read_database_snapshot(db)
    files = set(path.iterdir())
    response = client.post("/backup/compare", json={"before_filename": "before.hibackup"})
    assert response.status_code == 200
    result = response.json()
    assert result["total_changes"] == 0
    assert result["changes"] == []
    assert {row["table"] for row in result["tables"]} == set(Base.metadata.tables)
    assert result["before"]["filename"] == "before.hibackup"
    assert result["after"]["filename"] is None
    with Session(engine) as db:
        assert backup.read_database_snapshot(db) == before
    assert set(path.iterdir()) == files


def test_current_and_two_backup_comparisons_have_same_results(comparison_context):
    client, engine, path, _role = comparison_context
    items = Base.metadata.tables["items"]
    with engine.begin() as connection:
        connection.execute(items.update().where(items.c.id == 1).values(quantity=4))
        connection.execute(items.insert().values(id=2, name="Riso", quantity=1, inventory_id=1))
    with Session(engine) as db:
        backup.create_backup(db, prefix="after")
    after_path = next(path.glob("after_*.hibackup"))
    live = client.post("/backup/compare", json={"before_filename": "before.hibackup"})
    archived = client.post("/backup/compare", json={
        "before_filename": "before.hibackup", "after_filename": after_path.name,
    })
    assert live.status_code == archived.status_code == 200
    assert live.json()["tables"] == archived.json()["tables"]
    assert live.json()["changes"] == archived.json()["changes"]
    assert live.json()["total_changes"] == 2
    changes = {change["key"]["id"]: change for change in live.json()["changes"]}
    assert changes[1]["kind"] == "modified"
    assert changes[1]["fields"] == [{
        "field": "quantity", "before": 2, "after": 4,
        "before_present": True, "after_present": True,
    }]
    assert changes[2]["kind"] == "added"
    reversed_result = client.post("/backup/compare", json={
        "before_filename": after_path.name, "after_filename": "before.hibackup",
    }).json()
    assert any(change["kind"] == "removed" for change in reversed_result["changes"])
    with Session(engine) as db:
        assert db.execute(select(items.c.quantity).where(items.c.id == 1)).scalar_one() == 4


def test_redaction_does_not_hide_changes():
    before = {
        "users": [{"id": 1, "hashed_password": "old-password"}],
        "settings": [{"key": "CUSTOM_SETTING", "value": "old-credential"}],
        "filter_templates": [{"id": 1, "criteria": {"token": "old-token", "nested": [{"secret": "old-secret"}]}}],
        "item_versions": [{"id": 1, "diff": '{"password": {"from": "a", "to": "private-value"}}'}],
    }
    after = {
        "users": [{"id": 1, "hashed_password": "new-password"}],
        "settings": [{"key": "CUSTOM_SETTING", "value": "new-credential"}],
        "filter_templates": [{"id": 1, "criteria": {"token": "new-token", "nested": [{"secret": "new-secret"}]}}],
        "item_versions": [{"id": 1, "diff": '{"password": {"from": "b", "to": "other-private-value"}}'}],
    }
    result = compare_snapshots(before, after)
    serialized = json.dumps(result)
    for private in ["old-password", "new-password", "old-credential", "new-credential", "old-token", "new-token", "old-secret", "new-secret", "private-value"]:
        assert private not in serialized
    assert result["total_changes"] == 4
    assert REDACTED in serialized


def test_pagination_composite_keys_table_filter_and_schema_differences():
    before = {
        "user_group_association": [
            {"user_id": 1, "group_id": 2},
            {"user_id": 1, "group_id": 3},
        ],
        "items": [{"id": 1, "description": None}],
    }
    after = {
        "user_group_association": [{"user_id": 1, "group_id": 3}],
        "items": [{"id": 1, "description": None, "priority": 0}],
        "settings": [],
    }
    all_changes = compare_snapshots(before, after)
    first_page = compare_snapshots(before, after, limit=1)
    second_page = compare_snapshots(before, after, offset=1, limit=1)
    assert first_page["total_changes"] == second_page["total_changes"] == 2
    assert first_page["changes"] + second_page["changes"] == all_changes["changes"]
    filtered = compare_snapshots(before, after, table_filter="user_group_association")
    assert filtered["total_changes"] == 1
    assert filtered["changes"][0]["key"] == {"user_id": 1, "group_id": 2}
    priority = all_changes["changes"][0]["fields"][0]
    assert priority["field"] == "priority"
    assert priority["before_present"] is False
    assert priority["after_present"] is True
    assert priority["after"] == 0
    assert next(row for row in filtered["tables"] if row["table"] == "settings")["before_present"] is False


def test_typed_numeric_and_datetime_values_compare_semantically():
    old = {
        "item_metadata_values": [{"id": 1, "value_number": {"$hib_type": "decimal", "value": "1.0000"}}],
        "items": [{"id": 1, "data_ins": {"$hib_type": "datetime", "value": "2026-11-04T12:00:00+01:00"}}],
    }
    new = {
        "item_metadata_values": [{"id": 1, "value_number": Decimal("1")}],
        "items": [{"id": 1, "data_ins": datetime(2026, 11, 4, 11)}],
    }
    assert compare_snapshots(old, new)["total_changes"] == 0


def test_decimal_output_preserves_exact_values():
    result = compare_snapshots(
        {"item_metadata_values": [{"id": 1, "value_number": {"$hib_type": "decimal", "value": "1234567890.1234"}}]},
        {"item_metadata_values": [{"id": 1, "value_number": Decimal("1234567890.1235")}]},
    )
    field = result["changes"][0]["fields"][0]
    assert field["before"] == "1234567890.1234"
    assert field["after"] == "1234567890.1235"


@pytest.mark.parametrize("kind", ["added", "removed"])
def test_added_and_removed_records_redact_secrets(kind):
    rows = {
        "users": [{"id": 1, "hashed_password": "private-password"}],
        "settings": [{"key": "CUSTOM_KEY", "value": "private-setting"}],
    }
    result = compare_snapshots({} if kind == "added" else rows, rows if kind == "added" else {})
    assert result["total_changes"] == 2
    assert all(change["kind"] == kind for change in result["changes"])
    assert "private-password" not in json.dumps(result)
    assert "private-setting" not in json.dumps(result)
    assert REDACTED in json.dumps(result)


@pytest.mark.parametrize("rows", [
    {"unknown": []},
    {"items": [{"name": "missing-id"}]},
    {"items": [{"id": 1}, {"id": 1}]},
    {"items": [{"id": []}]},
    {"items": [{"id": True}]},
    {"items": [{"id": "1"}]},
])
def test_ambiguous_or_unknown_data_is_rejected(rows):
    with pytest.raises(ValueError):
        compare_snapshots(rows, {})


def test_invalid_archives_paths_and_paging_fail_explicitly(comparison_context):
    client, _engine, path, _role = comparison_context
    (path / "invalid.hibackup").write_bytes(b"not-a-zip")
    for filename, code in [
        ("../before.hibackup", 400),
        ("absent.hibackup", 404),
        ("invalid.hibackup", 400),
    ]:
        response = client.post("/backup/compare", json={"before_filename": filename})
        assert response.status_code == code
        assert "detail" in response.json()
    for paging in [{"offset": -1}, {"limit": 0}, {"limit": 101}]:
        assert client.post("/backup/compare", json={"before_filename": "before.hibackup", **paging}).status_code == 422
    assert client.post("/backup/compare", json={"before_filename": "before.hibackup", "table": "unknown"}).status_code == 400


@pytest.mark.parametrize("tables", [None, "items", {"items": []}, [42]])
def test_malformed_manifest_table_list_is_rejected(comparison_context, tables):
    client, _engine, path, _role = comparison_context
    metadata, _rows = read_backup_archive(path / "before.hibackup")
    metadata["tables"] = tables
    write_backup_archive(path / "invalid.hibackup", metadata, [])
    response = client.post("/backup/compare", json={"before_filename": "invalid.hibackup"})
    assert response.status_code == 400
    assert "detail" in response.json()


@pytest.mark.parametrize("table,field,value", [
    ("items", "data_ins", {"$hib_type": "datetime"}),
    ("items", "data_ins", {"$hib_type": "datetime", "value": "invalid-private-date"}),
    ("item_metadata_values", "value_number", {"$hib_type": "decimal", "value": "invalid-private-decimal"}),
    ("item_metadata_values", "value_number", {"$hib_type": "decimal", "value": "NaN"}),
    ("item_metadata_values", "value_number", {"$hib_type": "decimal", "value": "Infinity"}),
])
def test_malformed_typed_values_fail_without_leaking_data(comparison_context, table, field, value):
    client, _engine, path, _role = comparison_context
    metadata, _rows = read_backup_archive(path / "before.hibackup")
    write_backup_archive(path / "invalid.hibackup", metadata, [
        {"table": table, "row": {"id": 1, field: value}},
    ])
    response = client.post("/backup/compare", json={"before_filename": "invalid.hibackup"})
    assert response.status_code == 400
    assert "private" not in response.text


def test_older_revision_and_missing_columns_can_be_compared(comparison_context):
    client, _engine, path, _role = comparison_context
    metadata, _rows = read_backup_archive(path / "before.hibackup")
    metadata["db_alembic_version"] = "4ef54a6a9ff5"
    metadata["tables"] = ["items"]
    write_backup_archive(path / "old.hibackup", metadata, [
        {"table": "items", "row": {"id": 1, "name": "Pasta", "quantity": 2, "inventory_id": 1}},
    ])
    response = client.post("/backup/compare", json={"before_filename": "old.hibackup"})
    assert response.status_code == 200
    assert response.json()["before"]["db_alembic_version"] == "4ef54a6a9ff5"
    assert response.json()["total_changes"] > 0


def test_only_admins_can_compare(comparison_context):
    client, _engine, _path, role = comparison_context
    role.name = "viewer"
    assert client.post("/backup/compare", json={"before_filename": "before.hibackup"}).status_code == 403
    client.app.dependency_overrides.pop(get_current_user)
    assert client.post("/backup/compare", json={"before_filename": "before.hibackup"}).status_code == 401
