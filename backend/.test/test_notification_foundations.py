import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, event, inspect, select
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from backup_archive import create_backup_archive, read_backup_archive
from models import (
    Base, Notification, NotificationEvent, NotificationPreference, Role, User,
)
from notification_contracts import (
    ChecklistCompletedData,
    InventorySharedData,
    ItemQuantityChangedData,
    NotificationEventType,
    notification_event_adapter,
)

TABLES = {"notification_events", "notifications", "notification_preferences"}
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/a0b1c2d3e4f5_add_notification_foundations.py"
)


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        role = Role(name="viewer")
        db.add(role)
        db.flush()
        db.add(User(id=1, username="member", role_id=role.id))
        db.commit()
    yield engine
    engine.dispose()


@pytest.mark.parametrize("data", [
    InventorySharedData(inventory_id=1, recipient_kind="user", recipient_id=2),
    InventorySharedData(inventory_id=1, recipient_kind="group", recipient_id=2),
    ItemQuantityChangedData(inventory_id=1, item_id=2, previous_quantity=5, quantity=2),
    ChecklistCompletedData(inventory_id=1),
])
def test_event_contract_round_trip(data):
    restored = notification_event_adapter.validate_json(data.model_dump_json())
    assert restored == data
    assert restored.model_dump(mode="json") == data.model_dump(mode="json")
    assert data.event_type in {kind.value for kind in NotificationEventType}


@pytest.mark.parametrize("payload", [
    {"event_type": "unknown", "inventory_id": 1},
    {"event_type": "checklist_completed", "inventory_id": 0},
    {"event_type": "checklist_completed", "inventory_id": "1"},
    {"event_type": "checklist_completed", "inventory_id": True},
    {"event_type": "checklist_completed", "inventory_id": 1, "password": "forbidden"},
    {"event_type": "inventory_shared", "inventory_id": 1, "recipient_kind": "all", "recipient_id": 2},
    {"event_type": "inventory_shared", "inventory_id": 1, "recipient_kind": "user"},
    {"event_type": "item_quantity_changed", "inventory_id": 1, "item_id": 2,
     "previous_quantity": 2, "quantity": 2},
])
def test_invalid_or_no_op_event_rejected(payload):
    with pytest.raises(ValidationError):
        notification_event_adapter.validate_python(payload)


def test_defaults_and_single_inbox_entry_per_event_user(engine):
    with Session(engine) as db:
        record = NotificationEvent(
            actor_id=1, payload=ChecklistCompletedData(inventory_id=1).model_dump(mode="json"),
        )
        preference = NotificationPreference(user_id=1, event_type="checklist_completed")
        db.add_all([record, preference])
        db.flush()
        assert record.event_key
        assert record.schema_version == 1
        assert record.status == "pending"
        assert record.attempts == 0
        assert record.created_at is not None
        assert record.available_at is not None
        assert preference.in_app_enabled is True
        assert preference.push_enabled is False
        assert preference.include_own_actions is False
        db.add(Notification(event_id=record.id, user_id=1))
        db.commit()
        event_id = record.id
        db.add(Notification(event_id=event_id, user_id=1))
        with pytest.raises(IntegrityError):
            db.flush()


def test_event_and_change_rollback_together(engine):
    with Session(engine) as db:
        user = db.get(User, 1)
        user.username = "changed"
        db.add(NotificationEvent(payload=ChecklistCompletedData(inventory_id=1).model_dump(mode="json")))
        db.flush()
        db.rollback()
    with Session(engine) as db:
        assert db.get(User, 1).username == "member"
        assert db.scalars(select(NotificationEvent)).all() == []


def test_deleting_recipient_removes_inbox_and_preferences_not_event(engine):
    with Session(engine) as db:
        record = NotificationEvent(actor_id=1, payload={"event_type": "checklist_completed", "inventory_id": 1})
        db.add(record)
        db.flush()
        db.add_all([
            Notification(event_id=record.id, user_id=1),
            NotificationPreference(user_id=1, event_type="checklist_completed"),
        ])
        db.commit()
        db.execute(delete(User).where(User.id == 1))
        db.commit()
        db.expire_all()
        assert db.scalars(select(Notification)).all() == []
        assert db.scalars(select(NotificationPreference)).all() == []
        assert db.scalars(select(NotificationEvent)).one().actor_id is None


@pytest.mark.parametrize("model,values", [
    (NotificationEvent, {"payload": {}, "status": "invalid"}),
    (NotificationEvent, {"payload": {}, "attempts": -1}),
    (NotificationPreference, {"user_id": 1, "event_type": "invalid"}),
])
def test_database_constraints(engine, model, values):
    with Session(engine) as db:
        db.add(model(**values))
        with pytest.raises(IntegrityError):
            db.flush()


def test_duplicate_preference_and_event_key_rejected(engine):
    with Session(engine) as db:
        db.add_all([
            NotificationPreference(user_id=1, event_type="inventory_shared"),
            NotificationEvent(event_key="stable-key", payload={}),
        ])
        db.commit()
        db.add(NotificationPreference(user_id=1, event_type="inventory_shared"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        db.add(NotificationEvent(event_key="stable-key", payload={}))
        with pytest.raises(IntegrityError):
            db.flush()


def load_migration(path=MIGRATION):
    spec = importlib.util.spec_from_file_location("notification_foundations_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("already_bootstrapped", [False, True])
def test_migration_upgrade_matches_models_and_downgrade_preserves_users(engine, already_bootstrapped):
    migration = load_migration()
    worker_migration = load_migration(
        MIGRATION.parent / "b2c3d4e5f6a7_notification_worker_leases.py",
    )
    if not already_bootstrapped:
        for name in ("notifications", "notification_preferences", "notification_events"):
            Base.metadata.tables[name].drop(engine)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection, opts={
            "include_object": lambda obj, name, kind, reflected, compare_to:
                kind != "table" or name in TABLES,
        })
        with Operations.context(context):
            migration.upgrade()
            migration.upgrade()
            worker_migration.upgrade()
            worker_migration.upgrade()
            assert compare_metadata(context, Base.metadata) == []
            worker_migration.downgrade()
            migration.downgrade()
        assert not TABLES.intersection(inspect(connection).get_table_names())
        assert connection.execute(select(User.username)).scalar_one() == "member"


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect(), mysql.dialect()])
def test_notification_ddl_compiles_for_supported_databases(dialect):
    for name in TABLES:
        table = Base.metadata.tables[name]
        assert str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))


@pytest.mark.parametrize("bootstrap_current_models", [False, True])
def test_alembic_cli_bootstrap_upgrade_downgrade(tmp_path, bootstrap_current_models):
    database_path = tmp_path / "notifications.db"
    environment = {
        **os.environ,
        "DATABASE_TYPE": "SQLITE",
        "DATABASE_URL": f"sqlite:///{database_path}",
    }
    backend_dir = Path(__file__).resolve().parents[1]

    def run(*arguments):
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=backend_dir,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    if bootstrap_current_models:
        run("-c", "from database import init_db; init_db()")
    else:
        old_engine = create_engine(environment["DATABASE_URL"])
        Base.metadata.create_all(
            old_engine,
            tables=[table for table in Base.metadata.sorted_tables if table.name not in TABLES],
        )
        old_engine.dispose()
    run("-m", "alembic", "stamp", "9b0c1d2e3f4a")
    run("-m", "alembic", "upgrade", "head")
    run("-m", "notification_worker", "--status")
    run("-m", "notification_worker", "--once")
    run("-m", "alembic", "downgrade", "9b0c1d2e3f4a")
    run("-m", "alembic", "upgrade", "head")
    migrated_engine = create_engine(environment["DATABASE_URL"])
    try:
        assert TABLES.issubset(inspect(migrated_engine).get_table_names())
        with migrated_engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == "e7f8a9b0c1d2"
    finally:
        migrated_engine.dispose()


def test_backup_includes_event_inbox_and_preferences(engine, tmp_path):
    with Session(engine) as db:
        payload = ChecklistCompletedData(inventory_id=1).model_dump(mode="json")
        record = NotificationEvent(payload=payload, actor_id=1)
        db.add(record)
        db.flush()
        db.add_all([
            Notification(event_id=record.id, user_id=1),
            NotificationPreference(user_id=1, event_type="checklist_completed"),
        ])
        db.commit()
        path = tmp_path / "notifications.hibackup"
        create_backup_archive(db, path, {
            "format": "home-inventory-backup-v3",
            "format_version": 1,
            "db_alembic_version": "a0b1c2d3e4f5",
        })
    _, rows = read_backup_archive(path)
    assert rows["notification_events"][0]["payload"] == payload
    assert rows["notifications"][0]["user_id"] == 1
    assert rows["notification_preferences"][0]["push_enabled"] is False
