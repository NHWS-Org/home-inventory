import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from backup_archive import read_backup_archive
from legacy_backup import convert_legacy_backup
from models import Base
from routes import backup


REVISION = "f7a8b9c0d1e2"
METADATA = {
    "format": "home-inventory-backup-v2",
    "created_at": "2026-11-02T09:00:00Z",
    "db_alembic_version": REVISION,
}


def legacy_sql(extra=""):
    return (
        f"-- HI_BACKUP_META: {json.dumps(METADATA)}\n"
        "-- PostgreSQL database dump\n"
        "\\restrict abc123\n"
        "SET standard_conforming_strings = on;\n"
        "SELECT pg_catalog.set_config('search_path', '', false);\n"
        "ALTER TABLE public.roles DISABLE TRIGGER ALL;\n"
        f"INSERT INTO public.alembic_version (version_num) VALUES ('{REVISION}');\n"
        "INSERT INTO public.roles (id, name, user_ins) VALUES (1, 'admin', 1);\n"
        "INSERT INTO public.users (id, username, hashed_password, role_id) "
        "VALUES (1, 'admin', 'synthetic-hash', 1);\n"
        "INSERT INTO public.inventories (id, name, type, owner_id) "
        "VALUES (1, 'Kitchen', 'INVENTORY', 1);\n"
        'INSERT INTO "public"."items" ("id", "name", "inventory_id", "description", "quantity") '
        "VALUES (1, 'L''acqua; -- testo', 1, 'Prima riga\nSeconda riga', 2), "
        "(2, 'Altro', 1, E'Unicode: \\u00e8\\nBackslash: \\\\', NULL);\n"
        "INSERT INTO public.metadata_definitions (id, key, label, field_type, list_options) "
        """VALUES (1, 'options', 'Options', 'LIST', '["A", "B"]');\n"""
        "INSERT INTO public.item_metadata_values (id, item_id, definition_id, value_number) "
        "VALUES (1, 1, 1, 123.4500);\n"
        "ALTER TABLE public.roles ENABLE TRIGGER ALL;\n"
        "SELECT pg_catalog.setval('public.items_id_seq', 2, true);\n"
        f"{extra}\n"
        "\\unrestrict abc123\n"
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)
    app = FastAPI()
    app.include_router(backup.router, prefix="/backup")
    app.dependency_overrides[backup.router.dependencies[0].dependency] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def test_convert_and_restore_legacy_backup(tmp_path):
    output = tmp_path / "converted.hibackup"
    convert_legacy_backup(legacy_sql(), METADATA, output)
    metadata, rows = read_backup_archive(output)
    assert metadata["format"] == backup.BACKUP_FORMAT
    assert metadata["db_alembic_version"] == REVISION
    assert metadata["created_at"] == METADATA["created_at"]
    assert metadata["admin_user_id"] == 1
    assert rows["items"][0]["name"] == "L'acqua; -- testo"
    assert rows["items"][0]["description"] == "Prima riga\nSeconda riga"
    assert rows["items"][1]["description"] == "Unicode: è\nBackslash: \\"
    assert rows["metadata_definitions"][0]["list_options"] == ["A", "B"]
    assert rows["item_metadata_values"][0]["value_number"] == {
        "$hib_type": "decimal", "value": "123.4500",
    }
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"manifest.json", "data.jsonl"}
        assert archive.getinfo("data.jsonl").compress_type == zipfile.ZIP_DEFLATED
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with db.begin():
            backup._restore_backup_rows(
                db, rows,
                backup.RestoreRequest(
                    confirm=True, mode="advanced",
                    overwrite_users_roles=True, overwrite_admin=True,
                ),
                metadata,
            )
        for name, values in rows.items():
            count = db.execute(select(func.count()).select_from(Base.metadata.tables[name])).scalar_one()
            assert count == len(values)
    engine.dispose()


@pytest.mark.parametrize("extra", [
    "DROP TABLE users;",
    "COPY public.users FROM stdin;",
    "INSERT INTO public.items (id, name) VALUES (9, current_user);",
    "INSERT INTO public.items (id, name) VALUES (9, pg_read_file('/etc/passwd'));",
    "INSERT INTO private.items (id) VALUES (1);",
    "INSERT INTO public.unknown_table (id) VALUES (1);",
    "INSERT INTO public.items (unknown_column) VALUES (1);",
    "INSERT INTO public.items (id) VALUES (1, 2);",
    "INSERT INTO public.items (id) VALUES (",
    "INSERT INTO public.items (id) VALUES",
    "INSERT INTO public.items (id) VALUES (3),;",
    "INSERT INTO public.items (id, id) VALUES (3, 4);",
])
def test_unsupported_sql_is_rejected_without_output(tmp_path, extra):
    output = tmp_path / "rejected.hibackup"
    with pytest.raises(ValueError):
        convert_legacy_backup(legacy_sql(extra), METADATA, output)
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("metadata", [
    {},
    {**METADATA, "format": "unknown"},
    {**METADATA, "db_alembic_version": "other"},
    {**METADATA, "created_at": "invalid"},
    [],
])
def test_invalid_or_mismatched_metadata_is_rejected(tmp_path, metadata):
    with pytest.raises(ValueError):
        convert_legacy_backup(legacy_sql(), metadata, tmp_path / "invalid.hibackup")


def test_revision_in_sql_must_match_sidecar(tmp_path):
    sql = legacy_sql().replace(f"VALUES ('{REVISION}')", "VALUES ('other')")
    with pytest.raises(ValueError, match="revisione Alembic"):
        convert_legacy_backup(sql, METADATA, tmp_path / "invalid.hibackup")


def test_legacy_dump_without_embedded_metadata_is_supported(tmp_path):
    sql = legacy_sql().split("\n", 1)[1]
    output = tmp_path / "sidecar-only.hibackup"
    convert_legacy_backup(sql, METADATA, output)
    metadata, rows = read_backup_archive(output)
    assert metadata["db_alembic_version"] == REVISION
    assert len(rows["items"]) == 2


def test_upload_legacy_pair_converts_without_accessing_database(client, tmp_path, monkeypatch):
    def unexpected_database_access():
        pytest.fail("Upload must not access the database")

    monkeypatch.setattr(backup, "SessionLocal", unexpected_database_access)
    response = client.post("/backup/upload", files={
        "file": ("old.sql", legacy_sql().encode(), "application/sql"),
        "metadata_file": ("old.sql.meta.json", json.dumps(METADATA), "application/json"),
    })
    assert response.status_code == 200
    assert response.json()["converted"] is True
    output = tmp_path / response.json()["filename"]
    assert output.suffix == ".hibackup"
    metadata, rows = read_backup_archive(output)
    assert metadata["db_alembic_version"] == REVISION
    assert len(rows["items"]) == 2
    assert list(tmp_path.iterdir()) == [output]

    content = output.read_bytes()
    second = client.post("/backup/upload", files={
        "file": ("new.hibackup", content, "application/octet-stream"),
    })
    assert second.status_code == 200
    assert second.json()["converted"] is False


def write_legacy_pair(path, name="old.sql"):
    (path / name).write_text(legacy_sql(), encoding="utf-8")
    (path / f"{name}.meta.json").write_text(json.dumps(METADATA), encoding="utf-8")


def test_in_place_conversion_keeps_names_sources_and_data(client, tmp_path, monkeypatch):
    write_legacy_pair(tmp_path)
    original = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    monkeypatch.setattr(backup, "SessionLocal", lambda: pytest.fail("Conversion must not access DB"))
    response = client.post("/backup/convert-legacy/old.sql")
    assert response.status_code == 200
    assert response.json()["filename"] == "old.hibackup"
    metadata, rows = read_backup_archive(tmp_path / "old.hibackup")
    assert metadata["db_alembic_version"] == REVISION
    assert len(rows["items"]) == 2
    for name, content in original.items():
        assert (tmp_path / name).read_bytes() == content
    assert sorted(file.name for file in tmp_path.iterdir()) == [
        "old.hibackup", "old.sql", "old.sql.meta.json",
    ]
    archive = (tmp_path / "old.hibackup").read_bytes()
    assert client.post("/backup/convert-legacy/old.sql").status_code == 409
    assert (tmp_path / "old.hibackup").read_bytes() == archive
    assert client.request("DELETE", "/backup/legacy/old.sql", json=False).status_code == 400
    assert (tmp_path / "old.sql").exists()
    assert client.request("DELETE", "/backup/legacy/old.sql", json=True).status_code == 200
    assert list(tmp_path.iterdir()) == [tmp_path / "old.hibackup"]
    assert (tmp_path / "old.hibackup").read_bytes() == archive


def test_listing_includes_legacy_pairs_and_incomplete_sql(client, tmp_path, monkeypatch):
    write_legacy_pair(tmp_path)
    (tmp_path / "missing.sql").write_text(legacy_sql())
    (tmp_path / "orphan.sql.meta.json").write_text(json.dumps(METADATA))
    client.app.dependency_overrides[backup.get_db] = lambda: None
    monkeypatch.setattr(backup, "_get_alembic_version", lambda db: REVISION)
    response = client.get("/backup/")
    assert response.status_code == 200
    entries = {entry["filename"]: entry for entry in response.json()}
    assert set(entries) == {"old.sql", "missing.sql"}
    assert entries["old.sql"]["legacy"] is True
    assert entries["old.sql"]["has_metadata"] is True
    assert entries["missing.sql"]["has_metadata"] is False
    assert entries["old.sql"]["restorable_on_current_db"] is False
    assert entries["old.sql"]["size"] == sum(file.stat().st_size for file in [
        tmp_path / "old.sql", tmp_path / "old.sql.meta.json",
    ])


def test_in_place_conversion_rejects_missing_invalid_and_unsafe_sources(client, tmp_path):
    assert client.post("/backup/convert-legacy/missing.sql").status_code == 404
    write_legacy_pair(tmp_path)
    (tmp_path / "old.sql.meta.json").unlink()
    assert client.post("/backup/convert-legacy/old.sql").status_code == 404
    (tmp_path / "old.sql.meta.json").write_text("not-json")
    assert client.post("/backup/convert-legacy/old.sql").status_code == 400
    (tmp_path / "old.sql.meta.json").write_text(json.dumps(METADATA))
    (tmp_path / "old.sql").write_text("DROP TABLE users;")
    assert client.post("/backup/convert-legacy/old.sql").status_code == 400
    assert not (tmp_path / "old.hibackup").exists()
    assert not list(tmp_path.glob(".conversion-*"))
    for filename in [".hidden.sql", "old.hibackup", r"..\old.sql"]:
        assert client.post(f"/backup/convert-legacy/{filename}").status_code == 400
        assert client.request("DELETE", f"/backup/legacy/{filename}", json=True).status_code == 400


def test_in_place_conversion_rejects_external_symlinks(client, tmp_path):
    from fastapi import HTTPException

    outside = tmp_path.parent / f"{tmp_path.name}-outside.sql"
    outside.write_text(legacy_sql())
    try:
        (tmp_path / "linked.sql").symlink_to(outside)
        with pytest.raises(HTTPException) as exc:
            backup._safe_backup_path("linked.sql", extension=".sql")
        assert exc.value.status_code == 400
        assert client.post("/backup/convert-legacy/linked.sql").status_code == 400
        assert client.request("DELETE", "/backup/legacy/linked.sql", json=True).status_code == 400
        assert outside.exists()
    finally:
        outside.unlink()


def test_in_place_conversion_never_overwrites_concurrent_destination(client, tmp_path, monkeypatch):
    write_legacy_pair(tmp_path)
    convert = backup.convert_legacy_backup

    def competing_conversion(sql, metadata, destination):
        convert(sql, metadata, destination)
        (tmp_path / "old.hibackup").write_bytes(b"existing-archive")

    monkeypatch.setattr(backup, "convert_legacy_backup", competing_conversion)
    assert client.post("/backup/convert-legacy/old.sql").status_code == 409
    assert (tmp_path / "old.hibackup").read_bytes() == b"existing-archive"
    assert (tmp_path / "old.sql").is_file()
    assert (tmp_path / "old.sql.meta.json").is_file()
    assert not list(tmp_path.glob(".conversion-*"))


def test_legacy_delete_surfaces_partial_failure_and_can_be_retried(client, tmp_path, monkeypatch):
    from pathlib import Path

    write_legacy_pair(tmp_path)
    unlink = Path.unlink

    def fail_sql(path, *args, **kwargs):
        if path.name == "old.sql":
            raise PermissionError("test")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_sql)
        response = client.request("DELETE", "/backup/legacy/old.sql", json=True)
    assert response.status_code == 500
    assert "incompleta" in response.json()["detail"]
    assert (tmp_path / "old.sql").exists()
    assert client.request("DELETE", "/backup/legacy/old.sql", json=True).status_code == 200
    assert not list(tmp_path.iterdir())


def test_legacy_endpoints_require_login(client):
    client.app.dependency_overrides.clear()
    assert client.post("/backup/convert-legacy/old.sql").status_code == 401
    assert client.request("DELETE", "/backup/legacy/old.sql", json=True).status_code == 401


@pytest.mark.parametrize("sidecar_name,sidecar_content", [
    (None, None),
    ("wrong.sql.meta.json", json.dumps(METADATA)),
    ("old.sql.meta.json", "not-json"),
    ("old.sql.meta.json", json.dumps({**METADATA, "db_alembic_version": "other"})),
])
def test_invalid_upload_does_not_leave_files(client, tmp_path, sidecar_name, sidecar_content):
    files = {"file": ("old.sql", legacy_sql().encode(), "application/sql")}
    if sidecar_name:
        files["metadata_file"] = (sidecar_name, sidecar_content, "application/json")
    response = client.post("/backup/upload", files=files)
    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_upload_requires_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)
    app = FastAPI()
    app.include_router(backup.router, prefix="/backup")
    with TestClient(app) as client:
        response = client.post("/backup/upload", files={
            "file": ("old.sql", legacy_sql().encode(), "application/sql"),
            "metadata_file": ("old.sql.meta.json", json.dumps(METADATA), "application/json"),
        })
    assert response.status_code == 401
    assert list(tmp_path.iterdir()) == []
