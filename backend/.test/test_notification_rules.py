import pytest
from datetime import timedelta
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.schema import CreateTable
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dependencies import get_current_user, get_db
from models import (
    Base, Group, Inventory, Item, Notification, NotificationEvent, NotificationPreference,
    NotificationRule, Role, SharedInventory, SharedInventoryGroup, User, UserGroupAssociation,
    ListAssignment,
)
from notification_outbox import claim_event, process_claim, utcnow
from notification_rules import emit_item_change
from quantity_changes import QUANTITY_MERGE_WINDOW_SECONDS
from routes.inventory import share_base, share_with_group_base
from routes.notifications import router


@pytest.fixture
def setup():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([Role(id=1, name="admin"), Role(id=2, name="moderator"), Role(id=3, name="viewer")])
        db.flush()
        db.add_all([
            User(id=1, username="owner", role_id=2, is_blocked=False),
            User(id=2, username="viewer", role_id=3, is_blocked=False),
            User(id=3, username="stranger", role_id=3, is_blocked=False),
            User(id=4, username="admin", role_id=1, is_blocked=False),
            User(id=5, username="editor", role_id=2, is_blocked=False),
        ])
        db.flush()
        db.add_all([
            Inventory(id=1, name="Stock", type="INVENTORY", owner_id=1),
            Inventory(id=2, name="List", type="CHECKLIST", owner_id=1),
            Group(id=1, name="Family"),
        ])
        db.flush()
        db.add_all([
            SharedInventory(inventory_id=1, user_id=2),
            SharedInventory(inventory_id=1, user_id=5),
            SharedInventory(inventory_id=2, user_id=2),
            SharedInventory(inventory_id=2, user_id=5),
            UserGroupAssociation(user_id=2, group_id=1),
            SharedInventoryGroup(inventory_id=1, group_id=1),
            Item(id=1, name="Rice", quantity=5, inventory_id=1),
            Item(id=2, name="A", quantity=0, inventory_id=2),
            Item(id=3, name="B", quantity=0, inventory_id=2),
        ])
    app = FastAPI()
    app.include_router(router, prefix="/notifications")
    current = [1]

    def database():
        with factory() as db:
            yield db

    def user():
        with factory() as db:
            result = db.get(User, current[0])
            result.role
            result.group_associations
            return result

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = user
    yield factory, TestClient(app), current
    engine.dispose()


def create_rule(client, inventory=1, **values):
    payload = {
        "event_type": "item_quantity_changed", "threshold": 3,
        "recipients": [{"kind": "participants"}], **values,
    }
    response = client.post(f"/notifications/rules/{inventory}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def process_all(factory):
    now = utcnow() + timedelta(seconds=QUANTITY_MERGE_WINDOW_SECONDS)
    while (claim := claim_event(factory, now=now)) is not None:
        assert process_claim(factory, claim, now=now)


def quantity_change(factory, old, new, actor=1):
    with factory.begin() as db:
        item = db.get(Item, 1)
        item.quantity = new
        emit_item_change(db, item, {"quantity": old, "inventory_id": 1}, actor)


def test_rule_api_owner_admin_only_and_scope_validation(setup):
    factory, client, current = setup
    rule = create_rule(client)
    for user in (2, 3, 5):
        current[0] = user
        assert client.get("/notifications/rules/1").status_code == 403
        assert client.delete(f"/notifications/rules/1/{rule['id']}").status_code == 403
    current[0] = 4
    assert client.get("/notifications/rules/1").status_code == 200
    current[0] = 1
    for changes in (
        {"threshold": None}, {"threshold": -1},
        {"recipients": []}, {"recipients": [{"kind": "user", "id": 3}]},
        {"recipients": [{"kind": "owner", "id": 1}]},
        {"recipients": [{"kind": "group", "id": 99}]},
        {"recipients": [{"kind": "event_recipient"}]},
    ):
        response = client.post("/notifications/rules/1", json={
            "event_type": "item_quantity_changed", "threshold": 3,
            "recipients": [{"kind": "owner"}], **changes,
        })
        assert response.status_code == 422, response.text
    assert client.post("/notifications/rules/2", json={
        "event_type": "item_quantity_changed", "threshold": 3,
        "recipients": [{"kind": "owner"}],
    }).status_code == 422
    assert client.get("/notifications/rules/999").status_code == 404


def test_threshold_transition_rearms_and_deduplicates_rules_groups(setup):
    factory, client, current = setup
    create_rule(client)
    create_rule(client, recipients=[{"kind": "group", "id": 1}, {"kind": "user", "id": 2}])
    quantity_change(factory, 5, 2)
    process_all(factory)
    with factory() as db:
        rows = db.scalars(select(Notification)).all()
        assert sorted(row.user_id for row in rows) == [2, 5]
    quantity_change(factory, 2, 1)
    quantity_change(factory, 1, 1)
    process_all(factory)
    with factory() as db:
        assert len(db.scalars(select(Notification)).all()) == 2
        assert len(db.scalars(select(NotificationEvent)).all()) == 2
    quantity_change(factory, 1, 5)
    quantity_change(factory, 5, 2)
    process_all(factory)
    with factory() as db:
        assert len(db.scalars(select(Notification)).all()) == 4


def test_preferences_own_actions_and_revoked_access(setup):
    factory, client, current = setup
    create_rule(client)
    current[0] = 1
    assert client.put("/notifications/preferences/item_quantity_changed", json={
        "in_app_enabled": True, "include_own_actions": True,
    }).status_code == 200
    current[0] = 2
    assert client.put("/notifications/preferences/item_quantity_changed", json={
        "in_app_enabled": False,
    }).status_code == 200
    quantity_change(factory, 5, 2)
    with factory.begin() as db:
        db.get(User, 5).is_blocked = True
    process_all(factory)
    with factory() as db:
        assert [row.user_id for row in db.scalars(select(Notification))] == [1]
    current[0] = 1
    assert len(client.get("/notifications").json()) == 1
    current[0] = 2
    assert client.get("/notifications").json() == []
    assert client.put("/notifications/1/read").status_code == 404


def test_inbox_rechecks_authorization_and_read_ownership(setup):
    factory, client, current = setup
    create_rule(client, recipients=[{"kind": "user", "id": 5}])
    quantity_change(factory, 5, 2)
    process_all(factory)
    current[0] = 5
    row = client.get("/notifications").json()[0]
    assert client.put(f"/notifications/{row['id']}/read").status_code == 200
    with factory.begin() as db:
        share = db.scalar(select(SharedInventory).where(
            SharedInventory.user_id == 5, SharedInventory.inventory_id == 1,
        ))
        db.delete(share)
    assert client.get("/notifications").json() == []
    assert client.put(f"/notifications/{row['id']}/read").status_code == 404


def test_share_user_and_group_events_no_op_and_transaction(setup):
    factory, client, current = setup
    create_rule(client, event_type="inventory_shared", threshold=None,
                recipients=[{"kind": "event_recipient"}])
    with factory.begin() as db:
        share_base("INVENTORY", 1, "stranger", db, db.get(User, 1))
    process_all(factory)
    with factory() as db:
        assert [row.user_id for row in db.scalars(select(Notification))] == [3]
        assert len(db.scalars(select(NotificationEvent)).all()) == 1
        share_base("INVENTORY", 1, "stranger", db, db.get(User, 1))
        assert len(db.scalars(select(NotificationEvent)).all()) == 1
    with factory.begin() as db:
        db.add(Group(id=2, name="New"))
        db.flush()
        db.add(UserGroupAssociation(user_id=2, group_id=2))
    with factory() as db:
        share_with_group_base("INVENTORY", 1, 2, db, db.get(User, 1))
    process_all(factory)
    with factory() as db:
        assert sorted(row.user_id for row in db.scalars(select(Notification))) == [2, 3]


def test_completion_only_transition_other_user_and_recovery(setup):
    factory, client, current = setup
    create_rule(client, inventory=2, event_type="checklist_completed",
                threshold=None, recipients=[{"kind": "participants"}])
    def change(item_id, quantity):
        with factory.begin() as db:
            item = db.get(Item, item_id)
            old = item.quantity
            item.quantity = quantity
            emit_item_change(db, item, {"quantity": old, "inventory_id": 2}, 5)
    change(2, 1)
    process_all(factory)
    with factory() as db:
        assert db.scalars(select(NotificationEvent)).all() == []
    change(3, 1)
    change(3, 1)
    process_all(factory)
    with factory() as db:
        assert sorted(row.user_id for row in db.scalars(select(Notification))) == [1, 2]
    change(3, 0)
    change(3, 1)
    process_all(factory)
    with factory() as db:
        assert len(db.scalars(select(Notification)).all()) == 4


def test_no_rules_no_events_and_rollback(setup):
    factory, client, current = setup
    quantity_change(factory, 5, 2)
    with factory() as db:
        assert db.scalars(select(NotificationEvent)).all() == []
    create_rule(client)
    with factory() as db:
        item = db.get(Item, 1)
        item.quantity = 1
        emit_item_change(db, item, {"quantity": 5, "inventory_id": 1}, 1)
        db.flush()
        db.rollback()
    with factory() as db:
        assert db.get(Item, 1).quantity == 2
        assert db.scalars(select(NotificationEvent)).all() == []


def test_deleted_or_disabled_rule_suppresses_queued_event(setup):
    factory, client, current = setup
    rule = create_rule(client)
    quantity_change(factory, 5, 2)
    assert client.delete(f"/notifications/rules/1/{rule['id']}").status_code == 200
    process_all(factory)
    with factory() as db:
        assert db.scalars(select(Notification)).all() == []


def test_preference_defaults_and_bad_inputs(setup):
    _, client, _ = setup
    assert all(row["in_app_enabled"] and not row["include_own_actions"] and not row["push_enabled"]
               for row in client.get("/notifications/preferences").json())
    assert client.put("/notifications/preferences/unknown", json={}).status_code == 422
    assert client.put("/notifications/preferences/inventory_shared", json={
        "push_enabled": "true",
    }).status_code == 422
    assert client.put("/notifications/preferences/inventory_shared", json={
        "push_enabled": True,
    }).status_code == 200


def test_real_item_update_merges_notifications_with_audit_and_ignores_noop(setup):
    from routes.item import update_item
    from schemas import ItemUpdate

    factory, client, _ = setup
    create_rule(client)
    with factory() as db:
        user = db.get(User, 1)
        for quantity in (2, 1, 1):
            update_item(1, ItemUpdate(
                name="Rice", description=None, inventory_id=1, quantity=quantity,
            ), db=db, user=user)
    process_all(factory)
    with factory() as db:
        records = db.scalars(select(NotificationEvent)).all()
        assert len(records) == 1
        assert records[0].payload["previous_quantity"] == 5
        assert records[0].payload["quantity"] == 1
        assert len(db.scalars(select(Notification)).all()) == 2


def test_assignment_deduction_emits_stock_and_completion_together(setup):
    from routes.item import update_item
    from schemas import ItemUpdate

    factory, client, _ = setup
    create_rule(client)
    create_rule(client, inventory=2, event_type="checklist_completed", threshold=None)
    with factory.begin() as db:
        db.get(Item, 3).quantity = 1
        db.add(ListAssignment(list_item_id=2, source_item_id=1, qty=4))
    with factory() as db:
        update_item(2, ItemUpdate(
            name="A", description=None, inventory_id=2, quantity=1,
        ), on_insufficient=None, db=db, user=db.get(User, 1))
    process_all(factory)
    with factory() as db:
        records = db.scalars(select(NotificationEvent)).all()
        assert {record.payload["event_type"] for record in records} == {
            "item_quantity_changed", "checklist_completed",
        }
        assert db.get(Item, 1).quantity == 1
        assert len(db.scalars(select(Notification)).all()) == 4


def test_insufficient_assignment_stock_rolls_back_without_events(setup):
    from fastapi import HTTPException
    from routes.item import update_item
    from schemas import ItemUpdate

    factory, client, _ = setup
    create_rule(client)
    with factory.begin() as db:
        db.add(ListAssignment(list_item_id=2, source_item_id=1, qty=10))
    with factory() as db:
        with pytest.raises(HTTPException) as failure:
            update_item(2, ItemUpdate(
                name="A", description=None, inventory_id=2, quantity=1,
            ), on_insufficient=None, db=db, user=db.get(User, 1))
        assert failure.value.status_code == 409
        db.rollback()
    with factory() as db:
        assert db.scalars(select(NotificationEvent)).all() == []
        assert db.get(Item, 2).quantity == 0


def test_rule_edit_does_not_apply_to_old_queue_event(setup):
    factory, client, _ = setup
    rule = create_rule(client)
    quantity_change(factory, 5, 2)
    assert client.put(f"/notifications/rules/1/{rule['id']}", json={
        "event_type": "item_quantity_changed", "threshold": 4,
        "recipients": [{"kind": "participants"}],
    }).status_code == 200
    process_all(factory)
    with factory() as db:
        assert db.scalars(select(Notification)).all() == []


def test_rules_migration_schema_parity_and_downgrade(setup):
    from test_notification_foundations import MIGRATION, load_migration

    factory, client, _ = setup
    migration = load_migration(MIGRATION.parent / "c4d5e6f7a8b9_notification_rules.py")
    with factory.begin() as db:
        context = MigrationContext.configure(db.connection())
        with Operations.context(context):
            migration.downgrade()
            migration.upgrade()
            migration.upgrade()
            assert compare_metadata(context, Base.metadata) == []
        assert db.get(User, 1).username == "owner"
    create_rule(client)


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect(), mysql.dialect()])
def test_rules_schema_compiles_for_supported_databases(dialect):
    assert str(CreateTable(NotificationRule.__table__).compile(dialect=dialect))


def test_group_membership_revoked_before_processing_excludes_user(setup):
    factory, client, _ = setup
    create_rule(client, recipients=[{"kind": "group", "id": 1}])
    quantity_change(factory, 5, 2)
    with factory.begin() as db:
        db.delete(db.get(UserGroupAssociation, (2, 1)))
    process_all(factory)
    with factory() as db:
        assert db.scalars(select(Notification)).all() == []


def test_inbox_paginates_authorized_rows_and_never_other_users(setup):
    factory, client, current = setup
    create_rule(client)
    for _ in range(3):
        quantity_change(factory, 5, 2)
    process_all(factory)
    current[0] = 2
    first = client.get("/notifications?limit=1").json()
    second = client.get("/notifications?limit=1&offset=1").json()
    assert len(first) == len(second) == 1
    assert first[0]["id"] > second[0]["id"]
    current[0] = 3
    assert client.get("/notifications").json() == []
    assert client.put(f"/notifications/{first[0]['id']}/read").status_code == 404


def test_two_concurrent_checklist_updates_emit_one_completion(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from routes.item import update_item
    from schemas import ItemUpdate

    engine = create_engine(f"sqlite:///{tmp_path / 'completion.db'}", connect_args={"timeout": 15})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(Role(id=1, name="admin"))
        db.flush()
        db.add(User(id=1, username="admin", role_id=1))
        db.flush()
        db.add(Inventory(id=1, name="List", type="CHECKLIST", owner_id=1))
        db.flush()
        db.add_all([
            Item(id=1, inventory_id=1, name="A", quantity=0),
            Item(id=2, inventory_id=1, name="B", quantity=0),
            NotificationRule(
                inventory_id=1, event_type="checklist_completed",
                recipients=[{"kind": "owner"}],
            ),
        ])
    barrier = Barrier(2)

    def check(item_id):
        with factory() as db:
            user = db.get(User, 1)
            barrier.wait()
            update_item(item_id, ItemUpdate(
                name=str(item_id), description=None, inventory_id=1, quantity=1,
            ), on_insufficient=None, db=db, user=user)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(check, (1, 2)))
        with factory() as db:
            assert len(db.scalars(select(NotificationEvent)).all()) == 1
    finally:
        engine.dispose()


def test_direct_access_revoked_before_worker_suppresses_delivery(setup):
    factory, client, _ = setup
    create_rule(client, recipients=[{"kind": "user", "id": 5}])
    quantity_change(factory, 5, 2)
    with factory.begin() as db:
        db.delete(db.scalar(select(SharedInventory).where(
            SharedInventory.inventory_id == 1, SharedInventory.user_id == 5,
        )))
    process_all(factory)
    with factory() as db:
        assert db.scalars(select(Notification)).all() == []


def test_disabled_rule_does_not_emit_and_restore_removes_rules(setup):
    from routes.backup import RestoreRequest, _restore_backup_rows

    factory, client, _ = setup
    create_rule(client, enabled=False)
    quantity_change(factory, 5, 2)
    with factory() as db:
        assert db.scalars(select(NotificationEvent)).all() == []
        _restore_backup_rows(db, {}, RestoreRequest(confirm=True), {})
        db.commit()
        assert db.scalars(select(NotificationRule)).all() == []


@pytest.mark.parametrize("changes,expected", [
    ([(0, 2), (10, 1)], (5, 1)),
    ([(0, 4), (10, 2)], (5, 2)),
    ([(0, 2), (10, 4)], (5, 4)),
    ([(0, 2), (10, 5)], None),
    ([(0, 2), (10, 5), (11, 1)], (5, 1)),
])
def test_quantity_grace_matches_audit_net_change(setup, monkeypatch, changes, expected):
    from models import ItemVersion
    from routes import item as item_routes
    from schemas import ItemUpdate

    factory, client, _ = setup
    create_rule(client)
    start = utcnow()
    for offset, quantity in changes:
        now = start + timedelta(seconds=offset)
        monkeypatch.setattr(item_routes, "_utc_now_naive", lambda: now)
        with factory() as db:
            item_routes.update_item(1, ItemUpdate(
                name="Rice", description=None, inventory_id=1, quantity=quantity,
            ), on_insufficient=None, db=db, user=db.get(User, 1))
    due = now + timedelta(seconds=QUANTITY_MERGE_WINDOW_SECONDS)
    assert claim_event(factory, now=due - timedelta(microseconds=1)) is None
    with factory() as db:
        events = db.scalars(select(NotificationEvent)).all()
        versions = db.scalars(select(ItemVersion)).all()
        if expected is None:
            assert events == versions == []
        else:
            assert len(events) == len(versions) == 1
            assert events[0].available_at == due
            assert (
                events[0].payload["previous_quantity"], events[0].payload["quantity"],
            ) == expected
    claim = claim_event(factory, now=due)
    if expected is None:
        assert claim is None
    else:
        assert claim is not None
        assert process_claim(factory, claim, now=due)
    with factory() as db:
        assert len(db.scalars(select(Notification)).all()) == (
            2 if expected is not None and expected[0] >= 3 > expected[1] else 0
        )


@pytest.mark.parametrize("offset,actor", [
    (QUANTITY_MERGE_WINDOW_SECONDS + 1, 1),
    (1, 5),
])
def test_quantity_notifications_do_not_merge_separate_audit_windows(
    setup, monkeypatch, offset, actor,
):
    from routes import item as item_routes
    from schemas import ItemUpdate

    factory, client, _ = setup
    create_rule(client)
    start = utcnow()
    for elapsed, user_id, quantity in [(0, 1, 2), (offset, actor, 1)]:
        now = start + timedelta(seconds=elapsed)
        monkeypatch.setattr(item_routes, "_utc_now_naive", lambda: now)
        with factory() as db:
            item_routes.update_item(1, ItemUpdate(
                name="Rice", description=None, inventory_id=1, quantity=quantity,
            ), on_insufficient=None, db=db, user=db.get(User, user_id))
    with factory() as db:
        assert len(db.scalars(select(NotificationEvent)).all()) == 2


def test_completion_grace_cancelled_by_uncheck_and_rearmed(setup):
    factory, client, _ = setup
    create_rule(client, inventory=2, event_type="checklist_completed", threshold=None)
    start = utcnow()

    def change(item_id, quantity, offset):
        with factory.begin() as db:
            item = db.get(Item, item_id)
            old = item.quantity
            item.quantity = quantity
            emit_item_change(
                db, item, {"quantity": old, "inventory_id": 2}, 1,
                now=start + timedelta(seconds=offset),
            )

    change(2, 1, 0)
    change(3, 1, 1)
    assert claim_event(factory, now=start + timedelta(seconds=2)) is None
    change(2, 0, 2)
    with factory() as db:
        assert db.scalars(select(NotificationEvent)).all() == []
    change(2, 1, 3)
    due = start + timedelta(seconds=3 + QUANTITY_MERGE_WINDOW_SECONDS)
    assert claim_event(factory, now=due - timedelta(microseconds=1)) is None
    claim = claim_event(factory, now=due)
    assert claim is not None
    assert process_claim(factory, claim, now=due)
    with factory() as db:
        assert len(db.scalars(select(Notification)).all()) == 2


def test_quantity_noop_does_not_extend_grace_and_rollback_preserves_event(setup, monkeypatch):
    from routes import item as item_routes
    from schemas import ItemUpdate

    factory, client, _ = setup
    create_rule(client)
    start = utcnow()
    monkeypatch.setattr(item_routes, "_utc_now_naive", lambda: start)
    with factory() as db:
        item_routes.update_item(1, ItemUpdate(
            name="Rice", description=None, inventory_id=1, quantity=2,
        ), on_insufficient=None, db=db, user=db.get(User, 1))
    later = start + timedelta(seconds=10)
    monkeypatch.setattr(item_routes, "_utc_now_naive", lambda: later)
    with factory() as db:
        item_routes.update_item(1, ItemUpdate(
            name="Rice", description=None, inventory_id=1, quantity=2,
        ), on_insufficient=None, db=db, user=db.get(User, 1))
    with factory() as db:
        item = db.get(Item, 1)
        previous = item_routes._snapshot_item(item)
        item.quantity = 5
        item_routes._write_item_version(db, item, "UPDATE", db.get(User, 1), previous)
        db.flush()
        db.rollback()
    with factory() as db:
        record = db.scalars(select(NotificationEvent)).one()
        assert record.payload["quantity"] == db.get(Item, 1).quantity == 2
        assert record.available_at == start + timedelta(seconds=QUANTITY_MERGE_WINDOW_SECONDS)


def test_quantity_grace_constant_shared_with_history_and_assignment_undo():
    import assignment_service
    import notification_rules
    from routes import item

    assert (
        item.QUANTITY_MERGE_WINDOW_SECONDS
        == notification_rules.QUANTITY_MERGE_WINDOW_SECONDS
        == assignment_service.UNDO_WINDOW_SECONDS
        == QUANTITY_MERGE_WINDOW_SECONDS
    )
