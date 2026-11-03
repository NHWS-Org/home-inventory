import json

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from test_barcode_backend import ctx  # noqa: F401


def _create_checklist(ctx):
    response = ctx["client"].post("/checklist/", json={"name": "Lista"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_item(client, inventory_id, **fields):
    response = client.post(
        "/item/",
        json={"name": "Articolo", "quantity": 0, "inventory_id": inventory_id, **fields},
    )
    return response


def test_checklist_priority_defaults_is_validated_and_is_versioned(ctx):
    client = ctx["client"]
    checklist_id = _create_checklist(ctx)
    created = _create_item(client, checklist_id)
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["priority"] == 0
    assert item["version_num"] == 1
    listed_items = client.get(f"/checklist/item/{checklist_id}/")
    assert listed_items.status_code == 200, listed_items.text
    assert listed_items.json()[0]["priority"] == 0

    updated = client.patch(f"/item/{item['id']}", json={
        "name": item["name"],
        "description": None,
        "quantity": 0,
        "inventory_id": checklist_id,
        "priority": 2,
    })
    assert updated.status_code == 200, updated.text
    assert (updated.json()["priority"], updated.json()["version_num"]) == (2, 2)
    assert client.get(f"/checklist/item/{checklist_id}/").json()[0]["priority"] == 2

    updated = client.patch(f"/item/{item['id']}", json={
        "name": item["name"],
        "description": None,
        "quantity": 0,
        "inventory_id": checklist_id,
        "priority": -2,
    })
    assert updated.status_code == 200, updated.text
    assert (updated.json()["priority"], updated.json()["version_num"]) == (-2, 3)

    history = client.get(f"/item/{item['id']}/history")
    assert history.status_code == 200, history.text
    assert [version["priority"] for version in history.json()] == [0, 2, -2]
    assert json.loads(history.json()[1]["diff"]) == {"priority": {"from": 0, "to": 2}}
    assert json.loads(history.json()[2]["diff"]) == {"priority": {"from": 2, "to": -2}}

    rollback = client.post(f"/item/{item['id']}/rollback/2")
    assert rollback.status_code == 200, rollback.text
    assert (rollback.json()["priority"], rollback.json()["version_num"]) == (2, 4)
    assert json.loads(client.get(f"/item/{item['id']}/history").json()[-1]["diff"]) == {
        "priority": {"from": -2, "to": 2}
    }

    out_of_range = client.patch(f"/item/{item['id']}", json={
        "name": item["name"],
        "description": None,
        "quantity": 0,
        "inventory_id": checklist_id,
        "priority": 3,
    })
    assert out_of_range.status_code == 422


def test_priority_is_restricted_to_checklists_and_reset_when_moved(ctx):
    client = ctx["client"]
    rejected = _create_item(client, ctx["inv_a"], priority=1)
    assert rejected.status_code == 400
    assert "solo per le checklist" in rejected.json()["detail"]

    checklist_id = _create_checklist(ctx)
    item = _create_item(client, checklist_id, priority=2).json()
    moved = client.patch(f"/item/{item['id']}", json={
        "name": item["name"],
        "description": None,
        "quantity": 0,
        "inventory_id": ctx["inv_a"],
    })
    assert moved.status_code == 200, moved.text
    assert moved.json()["priority"] == 0
    assert moved.json()["inventory_id"] == ctx["inv_a"]
    history = client.get(f"/item/{item['id']}/history").json()
    assert json.loads(history[-1]["diff"]) == {
        "priority": {"from": 2, "to": 0},
        "inventory_id": {"from": checklist_id, "to": ctx["inv_a"]},
    }

    invalid_update = client.patch(f"/item/{item['id']}", json={
        "name": item["name"],
        "description": None,
        "quantity": 0,
        "inventory_id": ctx["inv_a"],
        "priority": -1,
    })
    assert invalid_update.status_code == 400


def test_priority_migration_backfills_existing_items_and_versions():
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "8a9b0c1d2e3f_add_checklist_item_priority.py"
    )
    spec = spec_from_file_location("checklist_item_priority_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE item_versions (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO items (id) VALUES (1)"))
        connection.execute(text("INSERT INTO item_versions (id) VALUES (1)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()

        assert {column["name"] for column in inspect(connection).get_columns("items")} == {
            "id", "priority",
        }
        assert {column["name"] for column in inspect(connection).get_columns("item_versions")} == {
            "id", "priority",
        }
        assert connection.execute(text("SELECT priority FROM items WHERE id = 1")).scalar_one() == 0
        assert connection.execute(text("SELECT priority FROM item_versions WHERE id = 1")).scalar_one() == 0
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "priority" not in {
            column["name"] for column in inspect(connection).get_columns("items")
        }
        assert "priority" not in {
            column["name"] for column in inspect(connection).get_columns("item_versions")
        }
    engine.dispose()
