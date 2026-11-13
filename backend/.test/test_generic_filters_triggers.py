from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import importlib
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, create_mock_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dependencies import get_current_user, get_db
from filter_contracts import FilterInput, RelativeDate, TriggerInput
from filter_service import date_value, evaluate_filter, filter_input
from models import (
    Base, FilterTemplate, Inventory, Item, ItemBarcode, ItemMetadataValue,
    MetadataDefinition, MetadataDefinitionAssignment, Notification, NotificationEvent,
    NotificationPreference, Role, ScheduledTrigger, SharedInventory, TriggerRun,
    TriggerSubscription, User,
)
from notification_outbox import claim_event, process_claim, utcnow
from routes.generic_filters import router as filter_router
from routes.notifications import router as inbox_router
from routes.triggers import router as trigger_router
from trigger_service import due_slot, next_slot, run_due_triggers, slot_on_day
from web_push import notification_push_payload


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
            User(id=2, username="editor", role_id=2),
            User(id=3, username="viewer", role_id=3),
            User(id=4, username="admin", role_id=1),
            User(id=5, username="stranger", role_id=2),
        ])
        db.flush()
        db.add_all([
            Inventory(id=1, name="Stock", type="INVENTORY", owner_id=1, data_ins=datetime(2020, 1, 1)),
            Inventory(id=2, name="List", type="CHECKLIST", owner_id=1, data_ins=datetime(2020, 1, 1)),
            Inventory(id=3, name="Secret", type="INVENTORY", owner_id=5, data_ins=datetime(2020, 1, 1)),
            MetadataDefinition(id=1, key="expiry", label="Scadenza", field_type="DATE"),
            MetadataDefinition(id=2, key="label", label="Etichetta", field_type="TEXT"),
            MetadataDefinition(id=3, key="private", label="Privato", field_type="TEXT"),
        ])
        db.flush()
        db.add_all([
            MetadataDefinitionAssignment(definition_id=1, scope="GLOBAL"),
            MetadataDefinitionAssignment(definition_id=2, scope="INVENTORY_TYPE", inventory_type="INVENTORY"),
            MetadataDefinitionAssignment(definition_id=3, scope="INVENTORY", inventory_id=3),
            *[SharedInventory(inventory_id=inventory, user_id=user) for inventory in (1, 2) for user in (2, 3)],
            Item(id=1, name="Rice", quantity=5, inventory_id=1, data_ins=datetime(2020, 1, 1)),
            Item(id=2, name="Milk", quantity=2, inventory_id=1, data_ins=datetime(2020, 1, 1)),
            Item(id=3, name="Buy milk", quantity=1, priority=2, inventory_id=2, data_ins=datetime(2020, 1, 1)),
            Item(id=4, name="Hidden rice", quantity=10, inventory_id=3),
        ])
        db.flush()
        db.add_all([
            ItemMetadataValue(item_id=1, definition_id=1, value_date=date(2026, 11, 13)),
            ItemMetadataValue(item_id=2, definition_id=1, value_date=date(2026, 11, 14)),
            ItemMetadataValue(item_id=1, definition_id=2, value_text="a%b"),
            ItemBarcode(item_id=2, code="012345"),
        ])
    app = FastAPI()
    for router, prefix in ((filter_router, "/filters"), (trigger_router, "/triggers"), (inbox_router, "/notifications")):
        app.include_router(router, prefix=prefix)
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


def criteria(**updates):
    return {
        "name": "Match", "description": None, "is_shared": False,
        "container_type": None, "match_mode": "all",
        "conditions": [{"source": "item", "field": "name", "operator": "contains", "value": "Rice"}],
        **updates,
    }


def create_schedule(client, **updates):
    saved = client.post("/filters", json=criteria()).json()
    response = client.post("/triggers", json={
        "name": "Daily", "filter_id": saved["id"], "enabled": True,
        "time": "10:00", "timezone": "Europe/Rome", "weekdays": list(range(1, 8)),
        "inventory_ids": None, "notify_mode": "always", **updates,
    })
    assert response.status_code == 201, response.text
    return saved, response.json()


def clock(factory, trigger_id, now):
    with factory.begin() as db:
        db.get(ScheduledTrigger, trigger_id).data_ins = now - timedelta(days=1)
    return now


def settle(factory, now):
    for _ in range(10):
        claim = claim_event(factory, now=now)
        if claim is None:
            return
        assert process_claim(factory, claim, now=now)
    pytest.fail("Outbox did not drain")


def test_filter_crud_catalog_permissions_and_preview(setup):
    factory, client, current = setup
    fields = client.get("/filters/fields").json()
    assert "private" not in [entry["field"] for entry in fields]
    assert {entry["field"] for entry in fields if entry["source"] == "item"} == {
        "name", "description", "quantity", "completed", "priority", "barcode", "created_at", "modified_at",
    }
    response = client.post("/filters", json=criteria())
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["can_manage"] and saved["trigger_count"] == 0
    assert saved["username_ins"] == "owner" and saved["data_ins"]
    assert client.get("/filters").json()[0]["username_ins"] == "owner"
    assert client.post(f"/filters/{saved['id']}/evaluate", json={}).json()["total_count"] == 1
    current[0] = 2
    assert client.get("/filters").json() == []
    assert client.get(f"/filters/{saved['id']}").status_code == 403
    current[0] = 1
    assert client.patch(f"/filters/{saved['id']}", json={"is_shared": True}).status_code == 200
    current[0] = 2
    assert client.get(f"/filters/{saved['id']}").json()["can_manage"] is False
    assert client.patch(f"/filters/{saved['id']}", json={"name": "Stolen"}).status_code == 403
    assert client.post("/filters/preview", json={**criteria(), "inventory_id": 3}).status_code == 403
    current[0] = 4
    assert client.delete(f"/filters/{saved['id']}").status_code == 200


def test_mixed_or_uses_union_not_intersection_and_null_is_guarded_by_scope(setup):
    factory, client, _ = setup
    payload = criteria(match_mode="any", conditions=[
        {"source": "item", "field": "completed", "operator": "equals", "value": True},
        {"source": "metadata", "field": "label", "definition_id": 2, "operator": "contains", "value": "%"},
    ])
    result = client.post("/filters/preview", json=payload)
    assert result.status_code == 200, result.text
    assert [container["item_ids"] for container in result.json()["containers"]] == [[1], [3]]
    payload["match_mode"] = "all"
    assert client.post("/filters/preview", json=payload).json()["total_count"] == 0
    payload["match_mode"] = "any"
    payload["conditions"] = [{"source": "metadata", "field": "label", "definition_id": 2, "operator": "is_null"}]
    assert client.post("/filters/preview", json=payload).json()["containers"][0]["item_ids"] == [2]
    payload["conditions"] = [{"source": "item", "field": "barcode", "operator": "is_not_null"}]
    assert client.post("/filters/preview", json=payload).json()["containers"][0]["item_ids"] == [2]


@pytest.mark.parametrize("conditions", [
    [{"source": "item", "field": "unknown", "operator": "equals", "value": 1}],
    [{"source": "item", "field": "quantity", "operator": "equals", "value": True}],
    [{"source": "item", "field": "barcode", "operator": "equals", "value": "012345"}],
    [{"source": "metadata", "field": "expiry", "definition_id": 1, "operator": "equals", "value": "2026-02-30"}],
    [{"source": "metadata", "field": "expiry", "definition_id": 1, "operator": "equals", "value": {"relative_days": True}}],
    [{"source": "metadata", "field": "expiry", "definition_id": 1, "operator": "equals", "value": {"relative_days": 36501}}],
    [{"source": "metadata", "field": "expiry", "definition_id": 1, "operator": "between",
      "range_from": {"relative_days": 1}, "range_to": {"relative_days": 0}}],
    [{"source": "item", "field": "name", "operator": "is_null", "value": "ignored"}],
])
def test_invalid_conditions_fail_visibly(setup, conditions):
    _, client, _ = setup
    assert client.post("/filters/preview", json=criteria(conditions=conditions)).status_code == 422


def test_relative_dates_ranges_and_item_local_day_dst(setup):
    factory, _, _ = setup
    with factory.begin() as db:
        user = db.get(User, 1)
        payload = FilterInput.model_validate(criteria(conditions=[
            {"source": "metadata", "field": "expiry", "definition_id": 1, "operator": "between",
             "range_from": {"relative_days": 0}, "range_to": {"relative_days": 1}},
        ]))
        assert evaluate_filter(db, user, payload, now=datetime(2026, 11, 13, 8))["total_count"] == 2
        # Rome 2026-03-29 is a 23-hour local calendar day.
        db.get(Item, 1).data_ins = datetime(2026, 3, 28, 23)
        db.get(Item, 2).data_ins = datetime(2026, 3, 29, 22)
        db.flush()
        payload = FilterInput.model_validate(criteria(conditions=[
            {"source": "item", "field": "created_at", "operator": "equals", "value": {"relative_days": 0}},
        ]))
        result = evaluate_filter(db, user, payload, now=datetime(2026, 3, 29, 10))
        assert result["containers"][0]["item_ids"] == [1]
    assert date_value(RelativeDate(relative_days=1), ZoneInfo("Europe/Rome"), datetime(2026, 12, 31, 12)) == date(2027, 1, 1)
    assert date_value(RelativeDate(relative_days=-1), ZoneInfo("Europe/Rome"), datetime(2024, 3, 1, 12)) == date(2024, 2, 29)
    assert date_value(RelativeDate(relative_days=0), ZoneInfo("America/New_York"), datetime(2026, 1, 1, 1)) == date(2025, 12, 31)


def test_legacy_adapter_keeps_original_saved_criteria_and_id(setup):
    factory, client, _ = setup
    raw = {"match_mode": "all", "criteria": [{"definition_id": 2, "operator": "contains", "value_text": "a%b"}]}
    with factory.begin() as db:
        template = FilterTemplate(name="Legacy", user_ins=1, filter_type="text", criteria=raw, is_shared=False)
        db.add(template)
        db.flush()
        template_id = template.id
    assert client.get(f"/filters/{template_id}").json()["conditions"][0]["value"] == "a%b"
    assert client.post(f"/filters/{template_id}/evaluate", json={}).json()["total_count"] == 1
    with factory() as db:
        assert db.get(FilterTemplate, template_id).criteria == raw
    with factory.begin() as db:
        db.get(FilterTemplate, template_id).criteria = {"criteria": [{"definition_id": 999, "operator": "equals", "value_text": "x"}]}
    invalid = client.get(f"/filters/{template_id}").json()
    assert invalid["validation_error"] and invalid["conditions"] == []
    assert client.patch(f"/filters/{template_id}", json={"name": "Silently repaired"}).status_code == 422
    with factory() as db:
        assert db.get(FilterTemplate, template_id).criteria["criteria"][0]["definition_id"] == 999
    assert client.post(f"/filters/{template_id}/evaluate", json={}).status_code == 422


@pytest.mark.parametrize(("match_mode", "expected"), [("any", [[1, 2]]), ("all", [])])
def test_legacy_mixed_type_match_modes_use_one_condition_per_row(setup, match_mode, expected):
    factory, client, _ = setup
    raw = {"match_mode": match_mode, "criteria": [
        {"definition_id": 2, "operator": "contains", "value_text": "a"},
        {"definition_id": 1, "operator": "equals", "value_date": "2026-11-14"},
    ]}
    with factory.begin() as db:
        template = FilterTemplate(name="Legacy mixed", user_ins=1, filter_type="text", criteria=raw, is_shared=False)
        db.add(template)
        db.flush()
        template_id = template.id
    result = client.post(f"/filters/{template_id}/evaluate", json={})
    assert result.status_code == 200, result.text
    assert [container["item_ids"] for container in result.json()["containers"]] == expected
    with factory() as db:
        assert db.get(FilterTemplate, template_id).criteria == raw


def test_scheduler_creator_delivery_dedupe_snapshots_and_private_revoke(setup):
    factory, client, current = setup
    saved, trigger = create_schedule(client)
    now = clock(factory, trigger["id"], datetime(2026, 11, 13, 9))
    assert client.put("/notifications/preferences/filter_trigger_matched", json={"in_app_enabled": True}).status_code == 200
    # Preference/subscription consent must predate this deterministic event.
    with factory.begin() as db:
        db.scalar(select(TriggerSubscription)).data_mod = now - timedelta(days=1)
        db.scalar(select(NotificationPreference)).data_mod = now - timedelta(days=1)
    assert run_due_triggers(factory, now=now) == 1
    assert run_due_triggers(factory, now=now + timedelta(minutes=10)) == 0
    settle(factory, now)
    rows = client.get("/notifications").json()
    assert len(rows) == 1 and rows[0]["event"]["count"] == 1
    assert rows[0]["event"]["filter_name"] == "Match"
    with factory.begin() as db:
        db.add(Item(id=5, name="Brown rice", quantity=1, inventory_id=1))
    assert client.post(f"/filters/{saved['id']}/evaluate", json={}).json()["total_count"] == 2
    # Delivered events are snapshots: current data changes do not rewrite the stored result count.
    assert client.get("/notifications").json()[0]["event"]["count"] == 1
    with factory() as db:
        record = db.scalar(select(NotificationEvent))
        assert record.actor_id is None
        assert "1 elementi" in notification_push_payload(db, record)["body"]
        assert db.query(TriggerRun).count() == 1
    current[0] = 2
    assert client.get(f"/triggers/{trigger['id']}").status_code == 403
    current[0] = 1
    assert client.patch(f"/filters/{saved['id']}", json={"name": "New name"}).status_code == 200
    assert client.get("/notifications").json() == []
    with factory() as db:
        assert db.query(NotificationEvent).count() == 0


def test_shared_subscriptions_current_permissions_and_consent(setup):
    factory, client, current = setup
    saved = client.post("/filters", json=criteria(is_shared=True)).json()
    response = client.post("/triggers", json={
        "name": "Shared daily", "filter_id": saved["id"], "time": "10:00", "weekdays": [5],
        "inventory_ids": [1], "notify_mode": "always",
    })
    assert response.status_code == 201, response.text
    trigger = response.json()
    assert trigger["username_ins"] == "owner" and trigger["data_ins"]
    current[0] = 2
    assert client.get(f"/triggers/{trigger['id']}").json()["can_manage"] is False
    assert client.put(f"/triggers/{trigger['id']}/subscription", json={"enabled": True}).status_code == 200
    assert client.get("/triggers/subscriptions").json() == [{"trigger_id": trigger["id"], "enabled": True}]
    assert client.put("/notifications/preferences/filter_trigger_matched", json={"in_app_enabled": True}).status_code == 200
    current[0] = 3
    assert client.put(f"/triggers/{trigger['id']}/subscription", json={"enabled": True}).status_code == 403
    now = clock(factory, trigger["id"], datetime(2026, 11, 13, 9))
    with factory.begin() as db:
        for row in db.scalars(select(TriggerSubscription)):
            row.data_mod = now - timedelta(days=1)
        db.scalar(select(NotificationPreference)).data_mod = now - timedelta(days=1)
    assert run_due_triggers(factory, now=now) == 1
    settle(factory, now)
    current[0] = 2
    assert len(client.get("/notifications").json()) == 1
    assert client.put(f"/triggers/{trigger['id']}/subscription", json={"enabled": False}).status_code == 200
    assert client.get("/notifications").json() == []
    current[0] = 1
    assert client.patch(f"/filters/{saved['id']}", json={"is_shared": False}).status_code == 200
    current[0] = 2
    assert client.get("/triggers").json() == []


def test_changed_compares_ids_empty_baseline_and_failure_record(setup):
    factory, client, _ = setup
    saved, trigger = create_schedule(client, notify_mode="changed")
    now = clock(factory, trigger["id"], datetime(2026, 11, 13, 9))
    assert run_due_triggers(factory, now=now) == 1
    assert run_due_triggers(factory, now=now + timedelta(days=1)) == 1
    with factory.begin() as db:
        assert db.query(NotificationEvent).count() == 1
        db.get(Item, 1).name = "Other"
        db.get(Item, 2).name = "Rice"
    assert run_due_triggers(factory, now=now + timedelta(days=2)) == 1
    with factory.begin() as db:
        assert db.query(NotificationEvent).count() == 2
        db.get(Item, 2).name = "Other"
    assert run_due_triggers(factory, now=now + timedelta(days=3)) == 1
    with factory.begin() as db:
        assert db.query(NotificationEvent).count() == 2
        assert db.get(ScheduledTrigger, trigger["id"]).baseline == {}
        db.get(Item, 1).name = "Rice"
    assert run_due_triggers(factory, now=now + timedelta(days=4)) == 1
    with factory.begin() as db:
        assert db.query(NotificationEvent).count() == 3
        db.get(User, 1).is_blocked = True
    assert run_due_triggers(factory, now=now + timedelta(days=5)) == 1
    assert run_due_triggers(factory, now=now + timedelta(days=5, minutes=10)) == 0
    with factory() as db:
        failed = db.scalar(select(TriggerRun).where(TriggerRun.status == "failed"))
        assert failed.error == "not_authorized"
        assert db.get(ScheduledTrigger, trigger["id"]).last_error == "not_authorized"


def test_dst_missing_repeated_time_catchup_and_schedule_changes():
    trigger = ScheduledTrigger(
        time="02:30", timezone="Europe/Rome", weekdays=list(range(1, 8)), enabled=True,
        data_ins=datetime(2026, 1, 1),
    )
    assert slot_on_day(trigger, date(2026, 3, 29)) is None
    assert slot_on_day(trigger, date(2026, 10, 25)) == datetime(2026, 10, 25, 0, 30)
    assert due_slot(trigger, datetime(2026, 10, 25, 1, 30)) == datetime(2026, 10, 25, 0, 30)
    assert due_slot(trigger, datetime(2026, 10, 25, 1, 31)) is None
    trigger.last_run_at = datetime(2026, 10, 25, 0, 30)
    trigger.time = "05:00"
    assert next_slot(trigger, datetime(2026, 10, 25, 1)) == datetime(2026, 10, 26, 4)
    with pytest.raises(ValidationError):
        TriggerInput(name="Bad", filter_id=1, time="24:00", weekdays=[1], timezone="Not/AZone")


def test_new_migration_matches_models_and_preserves_existing_preferences(setup):
    factory, _, _ = setup
    revision = importlib.import_module("migrations.versions.ba1c2d3e4f5a_generic_filters_scheduled_triggers")
    with factory.begin() as db:
        db.add(NotificationPreference(user_id=1, event_type="item_updated", in_app_enabled=True))
        db.flush()
        context = MigrationContext.configure(db.connection())
        with Operations.context(context):
            revision.downgrade()
            revision.upgrade()
        assert db.scalar(select(NotificationPreference)).in_app_enabled
        assert compare_metadata(context, Base.metadata) == []


def test_new_migration_accepts_current_model_bootstrap_without_recreating_tables(setup):
    factory, client, _ = setup
    saved, trigger = create_schedule(client)
    revision = importlib.import_module("migrations.versions.ba1c2d3e4f5a_generic_filters_scheduled_triggers")
    with factory.begin() as db:
        context = MigrationContext.configure(db.connection())
        with Operations.context(context):
            revision.upgrade()
            revision.upgrade()
        assert db.get(FilterTemplate, saved["id"]).name == "Match"
        assert db.get(ScheduledTrigger, trigger["id"]).name == "Daily"
        assert db.scalar(select(TriggerSubscription)).enabled
        assert compare_metadata(context, Base.metadata) == []


@pytest.mark.parametrize("mismatch", ["columns", "check"])
def test_new_migration_rejects_incompatible_existing_bootstrap_schema(setup, mismatch):
    factory, _, _ = setup
    revision = importlib.import_module("migrations.versions.ba1c2d3e4f5a_generic_filters_scheduled_triggers")
    with factory.begin() as db:
        context = MigrationContext.configure(db.connection())
        with Operations.context(context):
            from alembic import op
            with op.batch_alter_table("scheduled_triggers") as batch:
                if mismatch == "columns":
                    batch.drop_column("timezone")
                else:
                    batch.drop_constraint("ck_scheduled_triggers_mode", type_="check")
                    batch.create_check_constraint("ck_scheduled_triggers_mode", "notify_mode IN ('invalid')")
            with pytest.raises(RuntimeError, match="Bootstrap schema mismatch: scheduled_triggers"):
                revision.upgrade()


@pytest.mark.parametrize("dialect", ["postgresql", "mysql"])
def test_new_tables_compile_portably(dialect):
    statements = []
    engine = create_mock_engine(f"{dialect}://", lambda sql, *args, **kwargs: statements.append(str(sql.compile(dialect=engine.dialect))))
    for name in ("scheduled_triggers", "trigger_subscriptions", "trigger_runs"):
        Base.metadata.tables[name].create(engine)
    assert any("uq_trigger_runs_instant" in sql for sql in statements)


def test_two_workers_execute_one_atomic_slot(setup):
    factory, client, _ = setup
    _, trigger = create_schedule(client)
    now = clock(factory, trigger["id"], datetime(2026, 11, 13, 9))
    # A real file permits independent connections; keep the fixture inside the test directory.
    path = Path(__file__).parent / f".trigger-race-{uuid4().hex}.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 5})
    concurrent_factory = sessionmaker(bind=engine)
    try:
        Base.metadata.create_all(engine)
        with factory() as source, concurrent_factory.begin() as target:
            for table in Base.metadata.sorted_tables:
                rows = source.execute(select(table)).mappings().all()
                if rows:
                    target.execute(table.insert(), [dict(row) for row in rows])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run_due_triggers(concurrent_factory, now=now), range(2)))
        assert sum(results) == 1
        with concurrent_factory() as db:
            assert db.query(TriggerRun).count() == db.query(NotificationEvent).count() == 1
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)


def test_event_and_run_are_atomic_and_failed_slot_is_not_replayed(setup, monkeypatch):
    factory, client, _ = setup
    _, trigger = create_schedule(client)
    now = clock(factory, trigger["id"], datetime(2026, 11, 13, 9))
    import trigger_service
    enqueue = trigger_service.enqueue_event

    def fail_after_staging(*args, **kwargs):
        enqueue(*args, **kwargs)
        raise RuntimeError("private exception details")

    monkeypatch.setattr(trigger_service, "enqueue_event", fail_after_staging)
    assert run_due_triggers(factory, now=now) == 1
    assert run_due_triggers(factory, now=now) == 0
    with factory() as db:
        assert db.query(NotificationEvent).count() == 0
        assert db.scalar(select(TriggerRun)).status == "failed"
        row = db.get(ScheduledTrigger, trigger["id"])
        assert row.last_error == "evaluation_failed" and row.baseline is None


def test_backup_restore_keeps_schedule_consent_and_run_dedupe(setup):
    from backup_archive import read_database_snapshot
    from routes.backup import RestoreRequest, _restore_backup_rows

    factory, client, _ = setup
    _, trigger = create_schedule(client)
    now = clock(factory, trigger["id"], datetime(2026, 11, 13, 9))
    assert run_due_triggers(factory, now=now) == 1
    with factory.begin() as db:
        snapshot = read_database_snapshot(db)
        assert len(snapshot["scheduled_triggers"]) == len(snapshot["trigger_runs"]) == 1
        _restore_backup_rows(db, snapshot, RestoreRequest(confirm=True), {"admin_user_id": 4})
    with factory() as db:
        assert db.query(NotificationEvent).count() == 0
        assert db.query(ScheduledTrigger).count() == db.query(TriggerRun).count() == 1
        assert db.scalar(select(TriggerSubscription)).enabled
    assert run_due_triggers(factory, now=now) == 0


def test_new_migration_alembic_smoke_with_isolated_database():
    from sqlalchemy import inspect

    backend_dir = Path(__file__).resolve().parents[1]
    path = Path(__file__).parent / f".trigger-migration-{uuid4().hex}.db"
    url = f"sqlite:///{path.resolve()}"
    # Alembic runs out of process: env.py's fileConfig must not mutate this pytest process's loggers,
    # and DATABASE_URL must never point at the application's configured database.
    environment = {**os.environ, "DATABASE_TYPE": "SQLITE", "DATABASE_URL": url}

    def alembic(*arguments):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=backend_dir, env=environment, text=True, capture_output=True, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    engine = create_engine(url)
    revision = importlib.import_module("migrations.versions.ba1c2d3e4f5a_generic_filters_scheduled_triggers")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(Role.__table__.insert(), {"id": 1, "name": "moderator"})
            connection.execute(User.__table__.insert(), {"id": 1, "username": "migration-owner", "role_id": 1})
            connection.execute(NotificationPreference.__table__.insert(), {
                "user_id": 1, "event_type": "item_updated", "in_app_enabled": True,
            })
            with Operations.context(MigrationContext.configure(connection)):
                revision.downgrade()
        alembic("stamp", revision.down_revision)
        assert alembic("heads").split() == [revision.revision, "(head)"]
        alembic("upgrade", "head")
        with engine.begin() as connection:
            assert {"scheduled_triggers", "trigger_runs", "trigger_subscriptions"} <= set(inspect(connection).get_table_names())
            assert connection.execute(select(NotificationPreference.in_app_enabled)).scalar_one()
            connection.execute(NotificationPreference.__table__.insert(), {
                "user_id": 1, "event_type": "filter_trigger_matched", "in_app_enabled": False,
            })
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        alembic("downgrade", revision.down_revision)
        alembic("upgrade", "head")
        with engine.connect() as connection:
            assert connection.execute(select(NotificationPreference.event_type)).scalars().all() == ["item_updated"]
    finally:
        engine.dispose()
        path.unlink(missing_ok=True)
