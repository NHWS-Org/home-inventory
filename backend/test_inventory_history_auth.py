import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base
from dependencies import get_db
from models import User, Role, RoleEnum, InventoryVersion
from routes.auth import get_current_user


@pytest.fixture
def auth_ctx():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()

    admin_role = Role(name=RoleEnum.admin.value)
    mod_role = Role(name=RoleEnum.moderator.value)
    viewer_role = Role(name=RoleEnum.viewer.value)
    db.add_all([admin_role, mod_role, viewer_role])
    db.commit()

    admin_user = User(username="admin", hashed_password="x", role_id=admin_role.id)
    mod_owner = User(username="mod_owner", hashed_password="x", role_id=mod_role.id)
    mod_other = User(username="mod_other", hashed_password="x", role_id=mod_role.id)
    viewer_user = User(username="viewer", hashed_password="x", role_id=viewer_role.id)
    viewer_owner = User(username="viewer_owner", hashed_password="x", role_id=viewer_role.id)
    db.add_all([admin_user, mod_owner, mod_other, viewer_user, viewer_owner])
    db.commit()

    # Deleted inventory version history (inventory_id = 100, no live inventory in `inventories` table)
    inv_ver1 = InventoryVersion(
        inventory_id=100,
        name="Deleted Inventory",
        type="INVENTORY",
        owner_id=mod_owner.id,
        version_num=1,
        operation="CREATE",
        changed_by_id=mod_owner.id,
    )
    inv_ver2 = InventoryVersion(
        inventory_id=100,
        name="Deleted Inventory",
        type="INVENTORY",
        owner_id=mod_owner.id,
        version_num=2,
        operation="DELETE",
        changed_by_id=mod_owner.id,
    )

    # Deleted checklist version history (inventory_id = 200, no live checklist in `inventories` table)
    chk_ver1 = InventoryVersion(
        inventory_id=200,
        name="Deleted Checklist",
        type="CHECKLIST",
        owner_id=mod_owner.id,
        version_num=1,
        operation="CREATE",
        changed_by_id=mod_owner.id,
    )
    chk_ver2 = InventoryVersion(
        inventory_id=200,
        name="Deleted Checklist",
        type="CHECKLIST",
        owner_id=mod_owner.id,
        version_num=2,
        operation="DELETE",
        changed_by_id=mod_owner.id,
    )

    # Deleted inventory owned by viewer_owner (inventory_id = 300)
    inv_viewer_ver = InventoryVersion(
        inventory_id=300,
        name="Viewer Deleted Inventory",
        type="INVENTORY",
        owner_id=viewer_owner.id,
        version_num=1,
        operation="CREATE",
        changed_by_id=viewer_owner.id,
    )

    db.add_all([inv_ver1, inv_ver2, chk_ver1, chk_ver2, inv_viewer_ver])
    db.commit()

    state = {"user_id": mod_owner.id}

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def override_user():
        session = Session()
        try:
            yield session.get(User, state["user_id"])
        finally:
            session.close()

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    yield {
        "client": TestClient(app),
        "db": db,
        "admin_user": admin_user,
        "mod_owner": mod_owner,
        "mod_other": mod_other,
        "viewer_user": viewer_user,
        "viewer_owner": viewer_owner,
        "state": state,
    }

    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def test_deleted_inventory_history_non_owner_forbidden(auth_ctx):
    client = auth_ctx["client"]
    auth_ctx["state"]["user_id"] = auth_ctx["mod_other"].id

    res = client.get("/inventory/100/history")
    assert res.status_code == 403
    assert res.json()["detail"] == "Accesso negato"


def test_deleted_checklist_history_non_owner_forbidden(auth_ctx):
    client = auth_ctx["client"]
    auth_ctx["state"]["user_id"] = auth_ctx["mod_other"].id

    res = client.get("/checklist/200/history")
    assert res.status_code == 403
    assert res.json()["detail"] == "Accesso negato"


def test_deleted_inventory_history_viewer_forbidden(auth_ctx):
    client = auth_ctx["client"]
    # Even if viewer is the owner of the deleted inventory, viewer cannot access history
    auth_ctx["state"]["user_id"] = auth_ctx["viewer_owner"].id

    res = client.get("/inventory/300/history")
    assert res.status_code == 403
    assert res.json()["detail"] == "Accesso negato"


def test_nonexistent_inventory_and_checklist_history_not_found(auth_ctx):
    client = auth_ctx["client"]
    auth_ctx["state"]["user_id"] = auth_ctx["mod_owner"].id

    res_inv = client.get("/inventory/9999/history")
    assert res_inv.status_code == 404
    assert res_inv.json()["detail"] == "Inventario non trovato"

    res_chk = client.get("/checklist/9999/history")
    assert res_chk.status_code == 404
    assert res_chk.json()["detail"] == "Checklist non trovata"


def test_cross_type_history_not_found_and_not_leaked(auth_ctx):
    client = auth_ctx["client"]
    auth_ctx["state"]["user_id"] = auth_ctx["mod_owner"].id

    # 100 is INVENTORY; calling /checklist/100/history should return 404
    res_chk = client.get("/checklist/100/history")
    assert res_chk.status_code == 404

    # 200 is CHECKLIST; calling /inventory/200/history should return 404
    res_inv = client.get("/inventory/200/history")
    assert res_inv.status_code == 404


def test_owner_and_admin_can_access_deleted_history(auth_ctx):
    client = auth_ctx["client"]

    # Owner (moderator) can access deleted inventory and checklist history
    auth_ctx["state"]["user_id"] = auth_ctx["mod_owner"].id
    res_inv_owner = client.get("/inventory/100/history")
    assert res_inv_owner.status_code == 200
    assert len(res_inv_owner.json()) == 2

    res_chk_owner = client.get("/checklist/200/history")
    assert res_chk_owner.status_code == 200
    assert len(res_chk_owner.json()) == 2

    # Admin can also access deleted history
    auth_ctx["state"]["user_id"] = auth_ctx["admin_user"].id
    res_inv_admin = client.get("/inventory/100/history")
    assert res_inv_admin.status_code == 200
    assert len(res_inv_admin.json()) == 2
