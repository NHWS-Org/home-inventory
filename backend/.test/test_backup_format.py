from datetime import datetime
from decimal import Decimal
import zipfile

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event, select
from sqlalchemy.orm import Session

from backup_archive import create_backup_archive, decode_value, encode_value, read_backup_archive
from models import Base
from routes import backup


def _create_test_database(engine):
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    alembic_version = Table(
        "alembic_version",
        MetaData(),
        Column("version_num", String(32), primary_key=True),
    )
    alembic_version.create(engine)
    with engine.begin() as connection:
        connection.execute(
            alembic_version.insert().values(version_num="d4e5f6a7b8c9")
        )


def test_logical_backup_is_compressed_and_restorable(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)
    source_engine = create_engine("sqlite:///:memory:")
    target_engine = create_engine("sqlite:///:memory:")
    _create_test_database(source_engine)
    _create_test_database(target_engine)

    cache_table = Base.metadata.tables["barcode_product_cache"]
    fetched_at = datetime(2026, 10, 31, 12, 30)
    with Session(source_engine) as source_db:
        source_db.execute(
            cache_table.insert().values(
                code="1234567890123",
                found=True,
                name="Example",
                fetched_at=fetched_at,
            )
        )
        metadata = {
            "format": backup.BACKUP_FORMAT,
            "format_version": backup.BACKUP_FORMAT_VERSION,
            "created_at": "2026-10-31T12:30:00+00:00",
            "db_type": "SQLITE",
            "db_alembic_version": "d4e5f6a7b8c9",
        }
        backup_path = tmp_path / "test.hibackup"
        create_backup_archive(source_db, backup_path, metadata)

    with zipfile.ZipFile(backup_path) as archive:
        assert archive.getinfo("data.jsonl").compress_type == zipfile.ZIP_DEFLATED
    restored_metadata, rows = read_backup_archive(backup_path)
    archived_row = rows["barcode_product_cache"][0]
    assert archived_row["fetched_at"] == {
        "$hib_type": "datetime",
        "value": fetched_at.isoformat(),
    }

    with Session(target_engine) as target_db:
        with target_db.begin():
            backup._restore_backup_rows(
                target_db,
                rows,
                backup.RestoreRequest(confirm=True),
                restored_metadata,
            )
        restored_row = target_db.execute(
            select(cache_table).where(cache_table.c.code == "1234567890123")
        ).mappings().one()
        assert restored_row["fetched_at"] == fetched_at

    source_engine.dispose()
    target_engine.dispose()


def test_numeric_backup_values_keep_decimal_precision():
    column_type = Base.metadata.tables["item_metadata_values"].c.value_number.type
    encoded = encode_value(Decimal("123.4500"), column_type)
    assert encoded == {"$hib_type": "decimal", "value": "123.4500"}
    assert decode_value(encoded, column_type) == Decimal("123.4500")
    json_type = Base.metadata.tables["filter_templates"].c.criteria.type
    json_value = {"$hib_type": "date", "value": "kept as user data"}
    assert decode_value(json_value, json_type) == json_value


def test_base_restore_preserves_admin_and_remaps_user_foreign_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)
    source_engine = create_engine("sqlite:///:memory:")
    target_engine = create_engine("sqlite:///:memory:")
    _create_test_database(source_engine)
    _create_test_database(target_engine)

    roles = Base.metadata.tables["roles"]
    users = Base.metadata.tables["users"]
    inventories = Base.metadata.tables["inventories"]
    with source_engine.begin() as connection:
        connection.execute(roles.insert().values(id=1, name="admin"))
        connection.execute(
            users.insert().values(
                id=1,
                username="admin",
                hashed_password="source-admin",
                role_id=1,
            )
        )
        connection.execute(
            users.insert().values(
                id=2,
                username="member",
                hashed_password="member-password",
                role_id=1,
                user_ins=1,
            )
        )
        connection.execute(
            inventories.insert().values(
                id=1,
                name="Source inventory",
                type="INVENTORY",
                owner_id=1,
            )
        )

    with target_engine.begin() as connection:
        connection.execute(roles.insert().values(id=1, name="admin"))
        connection.execute(
            users.insert().values(
                id=5,
                username="admin",
                hashed_password="target-admin",
                role_id=1,
            )
        )
        connection.execute(
            users.insert().values(
                id=6,
                username="old-member",
                hashed_password="old-password",
                role_id=1,
            )
        )
        connection.execute(
            inventories.insert().values(
                id=99,
                name="Old inventory",
                type="INVENTORY",
                owner_id=6,
            )
        )

    backup_path = tmp_path / "source.hibackup"
    with Session(source_engine) as source_db:
        metadata = {
            "format": backup.BACKUP_FORMAT,
            "format_version": backup.BACKUP_FORMAT_VERSION,
            "created_at": "2026-10-31T12:30:00+00:00",
            "db_type": "SQLITE",
            "db_alembic_version": "d4e5f6a7b8c9",
        }
        create_backup_archive(source_db, backup_path, metadata)

    restored_metadata, rows = read_backup_archive(backup_path)
    with Session(target_engine) as target_db:
        with target_db.begin():
            backup._restore_backup_rows(
                target_db,
                rows,
                backup.RestoreRequest(confirm=True),
                restored_metadata,
            )
        assert target_db.execute(
            select(users.c.hashed_password).where(users.c.id == 5)
        ).scalar_one() == "target-admin"
        assert target_db.execute(
            select(users.c.username).where(users.c.id == 2)
        ).scalar_one() == "member"
        assert target_db.execute(
            select(users.c.user_ins).where(users.c.id == 2)
        ).scalar_one() == 5
        assert target_db.execute(
            select(inventories.c.owner_id).where(inventories.c.id == 1)
        ).scalar_one() == 5
        assert target_db.execute(
            select(users.c.id).where(users.c.id == 6)
        ).first() is None

    source_engine.dispose()
    target_engine.dispose()


def test_archive_exports_only_columns_present_in_legacy_schema(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    legacy_items = Table(
        "items",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("name", String),
        Column("inventory_id", Integer),
    )
    legacy_items.create(engine)
    with engine.begin() as connection:
        connection.execute(
            legacy_items.insert().values(id=7, name="Legacy item", inventory_id=3)
        )

    backup_path = tmp_path / "legacy.hibackup"
    metadata = {
        "format": backup.BACKUP_FORMAT,
        "format_version": backup.BACKUP_FORMAT_VERSION,
        "created_at": "2026-10-31T12:30:00+00:00",
        "db_type": "POSTGRES",
        "db_alembic_version": "4ef54a6a9ff5",
    }
    with Session(engine) as source_db:
        create_backup_archive(source_db, backup_path, metadata)

    _, rows = read_backup_archive(backup_path)
    assert rows["items"] == [
        {"id": 7, "name": "Legacy item", "inventory_id": 3}
    ]
    assert metadata["tables"] == ["items"]
    engine.dispose()
