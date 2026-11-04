import json

import pytest

from models import MetadataDefinition, MetadataDefinitionAssignment
from test_barcode_backend import ctx  # noqa: F401


def _create_item(client, inventory_id, description=None):
    response = client.post(
        "/item/",
        json={
            "name": "Articolo",
            "description": description,
            "quantity": 1,
            "inventory_id": inventory_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _update_item(client, item, description, quantity):
    response = client.patch(
        f"/item/{item['id']}",
        json={
            "name": item["name"],
            "description": description,
            "quantity": quantity,
            "inventory_id": item["inventory_id"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _history(client, item_id):
    response = client.get(f"/item/{item_id}/history")
    assert response.status_code == 200, response.text
    return response.json()


def _metadata_definition(ctx, key, field_type):
    db = ctx["db"]
    definition = MetadataDefinition(key=key, label=key, field_type=field_type)
    definition.assignments.append(MetadataDefinitionAssignment(scope="GLOBAL"))
    db.add(definition)
    db.commit()
    return definition.id


@pytest.mark.parametrize("before,after", [(None, ""), ("", None)])
def test_empty_description_is_omitted_from_quantity_diff(ctx, before, after):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"], before)

    updated = _update_item(client, item, after, 2)

    assert updated["description"] == after
    assert updated["version_num"] == 2
    history = _history(client, item["id"])
    assert len(history) == 2
    assert json.loads(history[-1]["diff"]) == {"quantity": {"from": 1, "to": 2}}

    audit = client.get("/audit/logs/items", params={"inventory_id": ctx["inv_a"]})
    assert audit.status_code == 200, audit.text
    update = next(log for log in audit.json() if log["item_id"] == item["id"] and log["operation"] == "UPDATE")
    assert json.loads(update["diff"]) == {"quantity": {"from": 1, "to": 2}}


@pytest.mark.parametrize("before,after", [(None, ""), ("", None)])
def test_empty_description_only_does_not_create_version(ctx, before, after):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"], before)

    updated = _update_item(client, item, after, 1)

    assert updated["description"] == after
    assert updated["version_num"] == 1
    assert [version["operation"] for version in _history(client, item["id"])] == ["CREATE"]

    rollback = client.post(f"/item/{item['id']}/rollback/1")
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["description"] == before
    assert rollback.json()["version_num"] == 1


@pytest.mark.parametrize(
    "before,after",
    [
        (None, "descrizione"),
        ("", "descrizione"),
        ("descrizione", None),
        ("descrizione", ""),
        (None, " "),
        (" ", None),
    ],
)
def test_real_description_changes_are_recorded(ctx, before, after):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"], before)

    updated = _update_item(client, item, after, 1)

    assert updated["version_num"] == 2
    assert json.loads(_history(client, item["id"])[-1]["diff"]) == {
        "description": {"from": before, "to": after}
    }


def test_empty_description_does_not_prevent_quantity_merge(ctx):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"])

    _update_item(client, item, "", 2)
    _update_item(client, item, "", 3)
    history = _history(client, item["id"])
    assert len(history) == 2
    assert json.loads(history[-1]["diff"]) == {"quantity": {"from": 1, "to": 3}}
    assert history[-1]["quantity"] == 3

    updated = _update_item(client, item, "", 1)
    assert updated["version_num"] == 1
    assert [version["operation"] for version in _history(client, item["id"])] == ["CREATE"]


def test_item_history_preserves_real_changes_rollback_and_deletion(ctx):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"])

    updated = _update_item(client, item, "descrizione", 2)
    assert updated["version_num"] == 2
    rollback = client.post(f"/item/{item['id']}/rollback/1")
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["version_num"] == 3
    assert rollback.json()["description"] is None
    assert rollback.json()["quantity"] == 1

    deleted = client.request("DELETE", f"/item/{item['id']}", json={"confirm": True})
    assert deleted.status_code == 200, deleted.text
    history = _history(client, item["id"])
    assert [version["operation"] for version in history] == ["CREATE", "UPDATE", "UPDATE", "DELETE"]
    assert json.loads(history[1]["diff"]) == {
        "description": {"from": None, "to": "descrizione"},
        "quantity": {"from": 1, "to": 2},
    }
    assert json.loads(history[2]["diff"]) == {
        "description": {"from": "descrizione", "to": None},
        "quantity": {"from": 2, "to": 1},
    }


@pytest.mark.parametrize("kind", ["inventory", "checklist"])
def test_unchanged_container_update_and_rollback_do_not_create_versions(ctx, kind):
    client = ctx["client"]
    response = client.post(f"/{kind}/", json={"name": "Originale"})
    assert response.status_code == 200, response.text
    inventory_id = response.json()["id"]

    response = client.patch(f"/{kind}/{inventory_id}", json={"name": "Originale"})
    assert response.status_code == 200, response.text
    assert response.json()["version_num"] == 1
    response = client.post(f"/{kind}/{inventory_id}/rollback/1")
    assert response.status_code == 200, response.text
    assert response.json()["version_num"] == 1

    response = client.patch(f"/{kind}/{inventory_id}", json={"name": "Nuovo"})
    assert response.status_code == 200, response.text
    assert response.json()["version_num"] == 2
    response = client.post(f"/{kind}/{inventory_id}/rollback/1")
    assert response.status_code == 200, response.text
    assert response.json()["version_num"] == 3
    assert response.json()["name"] == "Originale"

    history = client.get(f"/{kind}/{inventory_id}/history")
    assert history.status_code == 200, history.text
    assert [version["operation"] for version in history.json()] == ["CREATE", "UPDATE", "UPDATE"]
    assert json.loads(history.json()[1]["diff"]) == {"name": {"from": "Originale", "to": "Nuovo"}}
    assert json.loads(history.json()[2]["diff"]) == {"name": {"from": "Nuovo", "to": "Originale"}}


@pytest.mark.parametrize("method", ["patch", "bulk"])
def test_equivalent_numeric_metadata_does_not_create_versions(ctx, method):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"])
    definition_id = _metadata_definition(ctx, "prezzo", "NUMBER")
    created = client.post(
        "/metadata/values",
        json={"item_id": item["id"], "definition_id": definition_id, "value_number": "1"},
    )
    assert created.status_code == 201, created.text
    value_id = created.json()["id"]
    assert len(_history(client, item["id"])) == 2

    def update(value):
        if method == "patch":
            return client.patch(f"/metadata/values/{value_id}", json={"value_number": value})
        return client.put(
            "/metadata/values/bulk-upsert",
            json={"item_id": item["id"], "values": [{"definition_id": definition_id, "value_number": value}]},
        )

    for equivalent in ("1", "1.0", "1.0000", "1e0"):
        response = update(equivalent)
        assert response.status_code == 200, response.text
        assert len(_history(client, item["id"])) == 2

    response = update("2")
    assert response.status_code == 200, response.text
    history = _history(client, item["id"])
    assert len(history) == 3
    change = json.loads(history[-1]["diff"])["metadata"][0]
    assert change["from"] == {"value_number": "1.0000"}
    assert change["to"] == {"value_number": "2"}


def test_bulk_metadata_keeps_real_changes_and_discards_numeric_noop(ctx):
    client = ctx["client"]
    item = _create_item(client, ctx["inv_a"])
    number_id = _metadata_definition(ctx, "numero", "NUMBER")
    boolean_id = _metadata_definition(ctx, "attivo", "BOOLEAN")

    def update(number, boolean):
        return client.put(
            "/metadata/values/bulk-upsert",
            json={
                "item_id": item["id"],
                "values": [
                    {"definition_id": number_id, "value_number": number},
                    {"definition_id": boolean_id, "value_boolean": boolean},
                ],
            },
        )

    response = update("0", False)
    assert response.status_code == 200, response.text
    initial_changes = json.loads(_history(client, item["id"])[-1]["diff"])["metadata"]
    assert {change["definition_id"]: change["to"] for change in initial_changes} == {
        number_id: {"value_number": "0"},
        boolean_id: {"value_boolean": False},
    }

    response = update("0.0", True)
    assert response.status_code == 200, response.text

    history = _history(client, item["id"])
    assert len(history) == 3
    changes = json.loads(history[-1]["diff"])["metadata"]
    assert len(changes) == 1
    assert changes[0]["definition_id"] == boolean_id
    assert changes[0]["from"] == {"value_boolean": False}
    assert changes[0]["to"] == {"value_boolean": True}
