from datetime import datetime, timedelta
import importlib

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dependencies import get_current_user, get_db
from models import (
    Base, DeviceSession, Group, Inventory, Item, ItemBarcode, ItemVersion,
    Notification, NotificationEvent, NotificationPreference, PushDelivery, PushSubscription,
    Role, SharedInventory, SharedInventoryGroup, User, UserGroupAssociation,
)
from notification_contracts import InventoryUpdatedData, ItemQuantityChangedData, ItemUpdatedData
from notification_outbox import claim_event, enqueue_event, process_claim, utcnow
from notification_service import emit_item_change, evaluate_event
from quantity_changes import QUANTITY_MERGE_WINDOW_SECONDS
from routes.assignment import router as assignment_router
from routes.barcode import admin_router as barcode_router
from routes.inventory import checklist_router, inventory_router
from routes.item import router as item_router
from routes.metadata import router as metadata_router
from routes.notifications import router

KINDS = ("item_quantity_changed", "item_updated", "inventory_updated")


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([Role(id=1, name="admin"), Role(id=2, name="moderator"), Role(id=3, name="viewer")])
        db.flush()
        db.add_all([
            User(id=1, username="owner", role_id=2),
            User(id=2, username="viewer", role_id=3),
            User(id=3, username="stranger", role_id=2),
            User(id=4, username="admin", role_id=1),
            User(id=5, username="editor", role_id=2),
            User(id=6, username="group-editor", role_id=2),
            User(id=7, username="blocked", role_id=2, is_blocked=True),
        ])
        db.flush()
        db.add_all([
            Inventory(id=1, name="Stock", type="INVENTORY", owner_id=1),
            Inventory(id=2, name="List", type="CHECKLIST", owner_id=1),
            Inventory(id=3, name="Other", type="INVENTORY", owner_id=3),
            Group(id=1, name="Family"),
        ])
        db.flush()
        db.add_all([
            *[SharedInventory(inventory_id=container, user_id=user)
              for container in (1, 2) for user in (2, 5, 7)],
            *[UserGroupAssociation(user_id=user, group_id=1) for user in (2, 6)],
            *[SharedInventoryGroup(inventory_id=container, group_id=1) for container in (1, 2)],
            Item(id=1, name="Rice", quantity=5, inventory_id=1),
            Item(id=2, name="A", quantity=0, inventory_id=2),
            Item(id=3, name="B", quantity=0, inventory_id=2),
        ])
    app = FastAPI()
    for route, prefix in (
        (router, "/notifications"), (item_router, "/item"),
        (inventory_router, "/inventory"), (checklist_router, "/checklist"),
        (metadata_router, "/metadata"), (barcode_router, "/admin/barcode"),
        (assignment_router, "/assignment"),
    ):
        app.include_router(route, prefix=prefix)
    current = [1]

    def database():
        with factory() as db:
            yield db

    def user():
        with factory() as db:
            row = db.get(User, current[0])
            row.role
            row.group_associations
            return row

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = user
    yield factory, TestClient(app), current
    engine.dispose()


def settle(factory):
    now = utcnow() + timedelta(seconds=QUANTITY_MERGE_WINDOW_SECONDS + 1)
    while (claim := claim_event(factory, now=now)) is not None:
        assert process_claim(factory, claim, now=now)


def events(factory):
    with factory() as db:
        return [{key: value for key, value in row.payload.items() if key not in {"details", "action_at"}}
                for row in db.scalars(select(NotificationEvent).order_by(NotificationEvent.id))]


def enable(client, kind, **options):
    response = client.put(f"/notifications/preferences/{kind}", json={
        "in_app_enabled": True, "push_enabled": False, "include_own_actions": False, **options,
    })
    assert response.status_code == 200, response.text


def patch_item(client, item_id, **payload):
    existing = client.get(f"/item/{item_id}").json()
    response = client.patch(f"/item/{item_id}", json={
        **{key: existing[key] for key in ("name", "description", "inventory_id", "quantity")}, **payload,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_fallback_and_new_user_defaults_and_orm_defaults(setup):
    factory, client, current = setup
    expected = [{
        "event_type": kind, "in_app_enabled": kind == "item_quantity_changed",
        "push_enabled": False, "include_own_actions": False,
    } for kind in KINDS]
    assert client.get("/notifications/preferences").json() == expected
    for entry in expected:
        assert client.put(f"/notifications/preferences/{entry['event_type']}", json={}).json() == entry
    with factory.begin() as db:
        db.add(User(id=8, username="new", role_id=2))
    current[0] = 8
    assert client.get("/notifications/preferences").json() == expected
    with factory.begin() as db:
        rows = [NotificationPreference(user_id=8, event_type=kind) for kind in KINDS]
        db.add_all(rows)
        db.flush()
        assert [row.in_app_enabled for row in rows] == [True, False, False]
        assert all(not row.push_enabled and not row.include_own_actions for row in rows)
    assert client.get("/notifications/preferences").json() == expected


@pytest.mark.parametrize("item_id,initial,new", [(1, 5, 9), (1, 5, 2), (2, 0, 1), (2, 1, 0)])
def test_any_quantity_change_grace_recipients_and_payload(setup, item_id, initial, new):
    factory, client, current = setup
    with factory.begin() as db:
        db.get(Item, item_id).quantity = initial
    patch_item(client, item_id, quantity=new)
    assert claim_event(factory) is None
    assert events(factory) == [{
        "event_type": "item_quantity_changed", "inventory_id": 1 if item_id == 1 else 2,
        "item_id": item_id, "previous_quantity": initial, "quantity": new,
    }]
    settle(factory)
    with factory() as db:
        assert sorted(row.user_id for row in db.scalars(select(Notification))) == [4, 5, 6]
    current[0] = 5
    inbox = client.get("/notifications").json()
    assert len(inbox) == 1
    assert inbox[0]["item_name"] == ("Rice" if item_id == 1 else "A")
    assert inbox[0]["inventory_type"] == ("INVENTORY" if item_id == 1 else "CHECKLIST")
    assert client.get("/notifications/unread-count").json() == {"count": 1}
    assert client.put("/notifications/read-all").json() == {"updated": 1}
    assert client.get("/notifications/unread-count").json() == {"count": 0}


@pytest.mark.parametrize("item_id,initial,intermediate", [(1, 5, 2), (2, 0, 1)])
def test_net_cancellation_preserves_audit_merge(setup, item_id, initial, intermediate):
    factory, client, _ = setup
    patch_item(client, item_id, quantity=intermediate)
    patch_item(client, item_id, quantity=initial)
    assert events(factory) == []
    with factory() as db:
        assert db.scalars(select(ItemVersion).where(ItemVersion.item_id == item_id)).all() == []
    settle(factory)
    with factory() as db:
        assert db.scalars(select(Notification)).all() == []


def test_quantity_merge_and_exact_grace_boundary(setup):
    factory, _, _ = setup
    now = datetime(2026, 11, 7, 12)
    with factory.begin() as db:
        item = db.get(Item, 1)
        item.quantity = 7
        emit_item_change(db, item, {"inventory_id": 1, "quantity": 5}, 1, now=now)
    with factory.begin() as db:
        item = db.get(Item, 1)
        item.quantity = 8
        emit_item_change(db, item, {"inventory_id": 1, "quantity": 7}, 1, now=now + timedelta(seconds=10))
    assert len(events(factory)) == 1
    assert events(factory)[0]["previous_quantity"] == 5
    assert events(factory)[0]["quantity"] == 8
    assert claim_event(factory, now=now + timedelta(seconds=54)) is None
    claim = claim_event(factory, now=now + timedelta(seconds=55))
    assert claim is not None
    assert process_claim(factory, claim, now=now + timedelta(seconds=55))


def test_quantity_outside_grace_stays_separate_and_details_do_not_prevent_cancellation(setup):
    factory, client, _ = setup
    patch_item(client, 1, quantity=7)
    patch_item(client, 1, name="New name", quantity=5)
    assert events(factory) == [{
        "event_type": "item_updated", "inventory_id": 1, "item_id": 1,
        "changed_fields": ["name"],
    }]
    now = datetime(2026, 11, 7, 12)
    with factory.begin() as db:
        item = db.get(Item, 1)
        item.quantity = 7
        emit_item_change(db, item, {"inventory_id": 1, "quantity": 5}, 1, now=now)
    with factory.begin() as db:
        item = db.get(Item, 1)
        item.quantity = 5
        emit_item_change(db, item, {"inventory_id": 1, "quantity": 7}, 1, now=now + timedelta(seconds=46))
    assert len([row for row in events(factory) if row["event_type"] == "item_quantity_changed"]) == 2


def test_checklist_individual_checks_do_not_require_completion(setup):
    factory, client, _ = setup
    patch_item(client, 2, quantity=1)
    patch_item(client, 3, quantity=1)
    assert sorted(row["item_id"] for row in events(factory)) == [2, 3]
    assert all(row["event_type"] == "item_quantity_changed" for row in events(factory))


def test_mixed_quantity_and_details_defaults_and_noops(setup):
    factory, client, current = setup
    patch_item(client, 1, name="Rice", description="", quantity=5)
    assert events(factory) == []
    patch_item(client, 1, name="Brown rice", description="Bag", quantity=9)
    payloads = events(factory)
    assert [row["event_type"] for row in payloads] == ["item_updated", "item_quantity_changed"]
    assert payloads[0] == {
        "event_type": "item_updated", "inventory_id": 1, "item_id": 1,
        "changed_fields": ["description", "name"],
    }
    assert claim_event(factory) is not None  # Details are immediate, quantities are delayed.
    # Reclaim the leased details event together with the pending quantity event.
    settle_at = utcnow() + timedelta(seconds=62)
    while (claim := claim_event(factory, now=settle_at)) is not None:
        assert process_claim(factory, claim, now=settle_at)
    current[0] = 5
    assert [row["event"]["event_type"] for row in client.get("/notifications").json()] == ["item_quantity_changed"]
    enable(client, "item_updated")
    current[0] = 1
    patch_item(client, 1, description="New bag")
    patch_item(client, 1, description="New bag", quantity=9)
    assert len(events(factory)) == 3
    settle(factory)
    current[0] = 5
    assert client.get("/notifications").json()[0]["event"]["event_type"] == "item_updated"


def test_inbox_action_details_are_historical_and_action_time_precedes_delivery(setup):
    factory, client, current = setup
    current[0] = 4
    enable(client, "item_updated")
    enable(client, "inventory_updated")
    current[0] = 1
    patch_item(client, 1, name="First title", description="First description", quantity=6)
    patch_item(client, 1, name="Later title", description="Later description", quantity=7)
    client.patch("/inventory/1", json={"name": "First inventory"})
    client.patch("/inventory/1", json={"name": "Later inventory"})
    settle(factory)
    current[0] = 4
    rows = client.get("/notifications").json()
    details = [r["event"]["details"] for r in rows if r["event"]["event_type"] == "item_updated"]
    assert {"name": "First title", "description": "First description"} in details
    assert {"name": "Later title", "description": "Later description"} in details
    assert {"name": "First inventory"} in [r["event"]["details"] for r in rows if r["event"]["event_type"] == "inventory_updated"]
    quantity = next(r for r in rows if r["event"]["event_type"] == "item_quantity_changed")
    assert quantity["action_at"] == quantity["event"]["action_at"]
    assert datetime.fromisoformat(quantity["action_at"]) < datetime.fromisoformat(quantity["created_at"]) + timedelta(seconds=1)


@pytest.mark.parametrize("route", ["inventory", "checklist"])
def test_inventory_rename_rollback_noops_and_default_off(setup, route):
    factory, client, current = setup
    inventory_id = 1 if route == "inventory" else 2
    name = "Stock" if inventory_id == 1 else "List"
    assert client.patch(f"/{route}/{inventory_id}", json={"name": name}).status_code == 200
    assert events(factory) == []
    assert client.patch(f"/{route}/{inventory_id}", json={"name": "Renamed"}).status_code == 200
    assert events(factory) == [{
        "event_type": "inventory_updated", "inventory_id": inventory_id, "changed_fields": ["name"],
    }]
    settle(factory)
    with factory() as db:
        assert db.scalars(select(Notification)).all() == []
    current[0] = 5
    enable(client, "inventory_updated")
    current[0] = 1
    assert client.patch(f"/{route}/{inventory_id}", json={"name": "Again"}).status_code == 200
    assert client.post(f"/{route}/{inventory_id}/rollback/1").status_code == 200
    settle(factory)
    current[0] = 5
    rows = client.get("/notifications").json()
    assert len(rows) == 2
    assert all(row["item_name"] is None for row in rows)


@pytest.mark.parametrize("kind", KINDS)
def test_preferences_own_actions_and_idempotent_delivery(setup, kind):
    factory, client, current = setup
    enable(client, kind, include_own_actions=True)
    current[0] = 5
    enable(client, kind, in_app_enabled=False)
    with factory.begin() as db:
        payload = {
            "item_quantity_changed": ItemQuantityChangedData(inventory_id=1, item_id=1, previous_quantity=5, quantity=6),
            "item_updated": ItemUpdatedData(inventory_id=1, item_id=1, changed_fields=["name"]),
            "inventory_updated": InventoryUpdatedData(inventory_id=1, changed_fields=["name"]),
        }[kind]
        record = enqueue_event(db, payload, actor_id=1)
        db.flush()
        evaluate_event(db, record)
        db.flush()
        evaluate_event(db, record)
    with factory() as db:
        ids = sorted(row.user_id for row in db.scalars(select(Notification)))
        assert ids == ([1, 4, 6] if kind == "item_quantity_changed" else [1])


@pytest.mark.parametrize("change", ["user_share", "group_share", "blocked", "viewer", "deleted_item", "moved_item"])
def test_delivery_and_inbox_recheck_current_access_and_item(setup, change):
    factory, client, current = setup
    patch_item(client, 1, quantity=6)
    settle(factory)
    current[0] = 6 if change == "group_share" else 5
    inbox = client.get("/notifications").json()
    assert len(inbox) == 1
    notification_id = inbox[0]["id"]
    with factory.begin() as db:
        user_id = current[0]
        if change == "user_share":
            db.query(SharedInventory).filter_by(user_id=user_id, inventory_id=1).delete()
        elif change == "group_share":
            db.query(UserGroupAssociation).filter_by(user_id=user_id).delete()
        elif change == "blocked":
            db.get(User, user_id).is_blocked = True
        elif change == "viewer":
            db.get(User, user_id).role_id = 3
        elif change == "deleted_item":
            db.delete(db.get(Item, 1))
        elif change == "moved_item":
            db.get(Item, 1).inventory_id = 3
        record = enqueue_event(db, ItemQuantityChangedData(
            inventory_id=1, item_id=1, previous_quantity=6, quantity=7,
        ), actor_id=1)
        db.flush()
        record_id = record.id
    settle(factory)
    assert client.get("/notifications").json() == []
    assert client.get("/notifications/unread-count").json() == {"count": 0}
    assert client.put("/notifications/read-all").json() == {"updated": 0}
    assert client.put(f"/notifications/{notification_id}/read").status_code == 404
    with factory() as db:
        assert db.scalar(select(Notification.id).where(
            Notification.event_id == record_id, Notification.user_id == current[0],
        )) is None


def test_viewer_owner_still_cannot_receive_and_admin_global_semantics(setup):
    factory, client, _ = setup
    with factory.begin() as db:
        db.get(Inventory, 1).owner_id = 2
    patch_item(client, 2, quantity=1)
    settle(factory)
    with factory() as db:
        assert sorted(row.user_id for row in db.scalars(select(Notification))) == [4, 5, 6]
        record = enqueue_event(db, InventoryUpdatedData(
            inventory_id=1, changed_fields=["name"],
        ), actor_id=1)
        db.flush()
        from notification_service import event_recipients

        assert event_recipients(db, record) == {4, 5, 6}


def test_creation_and_restore_are_not_update_events_and_item_rollback_is(setup):
    factory, client, _ = setup
    response = client.post("/item/", json={"name": "New", "quantity": 1, "inventory_id": 1})
    assert response.status_code == 201
    assert events(factory) == []
    patch_item(client, 1, name="Changed", quantity=8)
    patch_item(client, 1, name="Again", quantity=9)
    response = client.post("/item/1/rollback/1")
    assert response.status_code == 200, response.text
    assert len([row for row in events(factory) if row["event_type"] == "item_updated"]) == 3
    assert response.json()["name"] == "Changed"
    assert response.json()["quantity"] == 8


def test_transfer_with_quantity_change_uses_current_container_and_noop_transfer_does_not_emit(setup):
    factory, client, current = setup
    current[0] = 4
    patch_item(client, 1, inventory_id=3, quantity=8)
    assert events(factory) == [
        {"event_type": "item_updated", "inventory_id": 3, "item_id": 1, "changed_fields": ["inventory_id"]},
        {"event_type": "item_quantity_changed", "inventory_id": 3, "item_id": 1, "previous_quantity": 5, "quantity": 8},
    ]
    patch_item(client, 1, inventory_id=3, quantity=8)
    assert len(events(factory)) == 2
    settle(factory)
    with factory() as db:
        assert [row.user_id for row in db.scalars(select(Notification))] == [3]


def test_barcodes_add_correct_format_noop_delete(setup):
    factory, client, current = setup
    response = client.post("/item/1/barcodes", json={"code": "ABC", "format": "qr_code"})
    assert response.status_code == 201, response.text
    barcode_id = response.json()["id"]
    assert events(factory)[0]["changed_fields"] == ["barcodes"]
    current[0] = 4
    path = f"/admin/barcode/codes/{barcode_id}"
    assert client.put(path, json={"code": "ABC", "format": "qr_code"}).status_code == 200
    assert len(events(factory)) == 1
    assert client.put(path, json={"code": "ABC", "format": "code_128"}).status_code == 200
    assert len(events(factory)) == 2
    assert client.put(path, json={"code": "XYZ", "format": "code_128"}).status_code == 200
    assert len(events(factory)) == 3
    assert client.delete(f"/item/1/barcodes/{barcode_id}").status_code == 200
    assert len(events(factory)) == 4
    assert all(row["changed_fields"] == ["barcodes"] for row in events(factory))


def create_metadata(client):
    response = client.post("/metadata/definitions", json={
        "key": "note", "label": "Note", "field_type": "TEXT",
    })
    assert response.status_code == 201, response.text
    definition_id = response.json()["id"]
    response = client.post(f"/metadata/definitions/{definition_id}/assignments", json={
        "scope": "GLOBAL",
    })
    assert response.status_code == 201, response.text
    return definition_id, response.json()["id"]


def test_metadata_value_all_mutations_and_shared_definition_changes(setup):
    factory, client, current = setup
    current[0] = 4
    definition_id, _ = create_metadata(client)
    assert len(events(factory)) == 3  # New applicable field changes all existing items.
    response = client.post("/metadata/values", json={
        "item_id": 1, "definition_id": definition_id, "value_text": "First",
    })
    assert response.status_code == 201, response.text
    value_id = response.json()["id"]
    assert len(events(factory)) == 4
    assert client.patch(f"/metadata/values/{value_id}", json={"value_text": "First"}).status_code == 200
    assert len(events(factory)) == 4
    assert client.patch(f"/metadata/values/{value_id}", json={"value_text": "Second"}).status_code == 200
    assert len(events(factory)) == 5
    assert client.put("/metadata/values/bulk-upsert", json={
        "item_id": 1, "values": [{"definition_id": definition_id, "value_text": "Second"}],
    }).status_code == 200
    assert len(events(factory)) == 5
    assert client.put("/metadata/values/bulk-upsert", json={
        "item_id": 1, "values": [{"definition_id": definition_id, "value_text": "Third"}],
    }).status_code == 200
    assert len(events(factory)) == 6
    path = f"/metadata/definitions/{definition_id}"
    assert client.patch(path, json={"label": "New label"}).status_code == 200
    assert len(events(factory)) == 9
    assert client.patch(path, json={"label": "New label"}).status_code == 200
    assert len(events(factory)) == 9
    assert client.delete(f"/metadata/values/{value_id}").status_code == 200
    assert len(events(factory)) == 10
    assert client.delete(path).status_code == 200
    assert len(events(factory)) == 13
    assert all(row["changed_fields"] == ["metadata"] for row in events(factory))


def test_metadata_scope_changes_only_when_effective_and_shared_value_deletion(setup):
    factory, client, current = setup
    current[0] = 4
    definition_id, global_assignment = create_metadata(client)
    response = client.post(f"/metadata/definitions/{definition_id}/assignments", json={
        "scope": "INVENTORY", "inventory_id": 1,
    })
    assert response.status_code == 201
    local_assignment = response.json()["id"]
    assert len(events(factory)) == 3  # Same field via redundant scope is not a mutation.
    assert client.delete(f"/metadata/assignments/{local_assignment}").status_code == 200
    assert len(events(factory)) == 3
    assert client.post("/metadata/values", json={
        "item_id": 1, "definition_id": definition_id, "value_text": "First",
    }).status_code == 201
    assert client.delete(f"/metadata/assignments/{global_assignment}").status_code == 200
    assert len(events(factory)) == 7
    assert client.delete(f"/metadata/definitions/{definition_id}").status_code == 200
    assert len(events(factory)) == 8  # Inapplicable stored value still disappeared.


def test_assignments_nonquantity_changes_and_check_stock_undo(setup):
    factory, client, _ = setup
    response = client.post("/assignment/", json={"list_item_id": 2, "source_item_id": 1, "qty": 2})
    assert response.status_code == 201, response.text
    assignment_id = response.json()["id"]
    assert sorted(row["item_id"] for row in events(factory)) == [1, 2]
    assert client.patch(f"/assignment/{assignment_id}", json={"qty": 2}).status_code == 200
    assert len(events(factory)) == 2
    assert client.patch(f"/assignment/{assignment_id}", json={"qty": 3}).status_code == 200
    assert len(events(factory)) == 4
    patch_item(client, 2, quantity=1)
    quantities = [row for row in events(factory) if row["event_type"] == "item_quantity_changed"]
    assert sorted((row["item_id"], row["previous_quantity"], row["quantity"]) for row in quantities) == [(1, 5, 2), (2, 0, 1)]
    patch_item(client, 2, quantity=0)
    assert len(events(factory)) == 4  # Both checklist and scarico cancelled.
    assert client.delete(f"/assignment/{assignment_id}").status_code == 200
    assert len(events(factory)) == 6


@pytest.mark.parametrize("deleted", ["list_item", "source_item", "checklist", "inventory"])
def test_assignment_cascade_notifies_surviving_items(setup, deleted):
    factory, client, _ = setup
    assert client.post("/assignment/", json={
        "list_item_id": 2, "source_item_id": 1, "qty": 2,
    }).status_code == 201
    if deleted.endswith("item"):
        item_id = 2 if deleted == "list_item" else 1
        response = client.request("DELETE", f"/item/{item_id}", json={"confirm": True})
    else:
        response = client.delete("/checklist/2" if deleted == "checklist" else "/inventory/1")
    assert response.status_code == 200, response.text
    assert events(factory)[-1] == {
        "event_type": "item_updated",
        "item_id": 1 if deleted in ("list_item", "checklist") else 2,
        "inventory_id": 1 if deleted in ("list_item", "checklist") else 2,
        "changed_fields": ["assignments" if deleted in ("list_item", "checklist") else "assignment"],
    }


def test_forward_migration_resets_old_choices_preserves_sessions_and_subscriptions():
    engine = create_engine("sqlite://")
    excluded = {"notification_events", "notifications", "notification_preferences", "push_deliveries", "push_subscriptions"}
    Base.metadata.create_all(engine, tables=[
        table for table in Base.metadata.sorted_tables if table.name not in excluded
    ])
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for name in (
                "a0b1c2d3e4f5_add_notification_foundations", "b2c3d4e5f6a7_notification_worker_leases",
                "c4d5e6f7a8b9_notification_rules", "f8a9b0c1d2e3_web_push",
            ):
                importlib.import_module(f"migrations.versions.{name}").upgrade()
        connection.execute(Role.__table__.insert(), {"id": 1, "name": "moderator"})
        connection.execute(User.__table__.insert(), [
            {"id": 1, "username": "existing", "role_id": 1},
            {"id": 2, "username": "existing-no-preferences", "role_id": 1},
        ])
        connection.execute(Inventory.__table__.insert(), {"id": 1, "owner_id": 1, "name": "Stock"})
        now = utcnow()
        connection.execute(DeviceSession.__table__.insert(), {
            "id": 1, "session_token_id": "stable", "user_id": 1,
            "created_at": now, "expires_at": now + timedelta(days=1),
        })
        connection.execute(PushSubscription.__table__.insert(), {
            "id": 1, "endpoint_hash": "hash", "endpoint": "private-endpoint", "p256dh": "key",
            "auth": "consent-key", "user_id": 1, "session_id": 1, "generation": "stable-generation",
            "vapid_fingerprint": "stable-fingerprint", "created_at": now,
            "updated_at": now, "expires_at": now + timedelta(days=1),
        })
        connection.exec_driver_sql(
            "INSERT INTO notification_rules (inventory_id,event_type,threshold,recipients,enabled)"
            " VALUES (1,'item_quantity_changed',3,'[]',1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO notification_preferences (user_id,event_type,in_app_enabled,push_enabled,include_own_actions)"
            " VALUES (1,'item_quantity_changed',0,1,1)"
        )
        connection.execute(NotificationEvent.__table__.insert(), {
            "id": 1, "event_key": "old", "payload": {"event_type": "checklist_completed", "inventory_id": 1},
        })
        connection.execute(Notification.__table__.insert(), {"event_id": 1, "user_id": 1})
        connection.execute(PushDelivery.__table__.insert(), {
            "event_id": 1, "subscription_id": 1, "generation": "stable-generation",
            "status": "sending", "created_at": now, "available_at": now, "expires_at": now + timedelta(days=1),
        })
        session_before = dict(connection.execute(select(DeviceSession.__table__)).mappings().one())
        subscription_before = dict(connection.execute(select(PushSubscription.__table__)).mappings().one())
        revision = importlib.import_module("migrations.versions.a9b0c1d2e3f4_personal_notification_preferences")
        with Operations.context(context):
            revision.upgrade()
        assert "notification_rules" not in inspect(connection).get_table_names()
        assert compare_metadata(context, Base.metadata) == []
        for table in (NotificationEvent, Notification, PushDelivery):
            assert connection.execute(select(table.__table__)).all() == []
        assert dict(connection.execute(select(DeviceSession.__table__)).mappings().one()) == session_before
        assert dict(connection.execute(select(PushSubscription.__table__)).mappings().one()) == subscription_before
        rows = connection.execute(select(NotificationPreference.__table__)).mappings().all()
        assert len(rows) == 6
        assert {(row["user_id"], row["event_type"], row["in_app_enabled"]) for row in rows} == {
            (user, kind, kind == "item_quantity_changed") for user in (1, 2) for kind in KINDS
        }
        assert all(not row["push_enabled"] and not row["include_own_actions"] for row in rows)
        with Operations.context(context), pytest.raises(RuntimeError, match="irreversible"):
            revision.downgrade()
    engine.dispose()
