import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base
from dependencies import get_db
from models import User, Role, RoleEnum, Inventory, Item, ItemVersion
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
    db.add_all([admin_user, mod_owner, mod_other, viewer_user])
    db.commit()

    # Create inventory owned by mod_owner
    inv1 = Inventory(id=1, name="Owner Inventory", owner_id=mod_owner.id, type="INVENTORY")
    db.add(inv1)
    db.commit()

    # Create an active item
    item_active = Item(id=10, name="Active Item", inventory_id=inv1.id, user_ins=mod_owner.id)
    db.add(item_active)
    db.commit()

    # ItemVersion for a deleted item (item_id = 20, no Item record in `items` table)
    item_ver1 = ItemVersion(
        item_id=20,
        inventory_id=inv1.id,
        name="Deleted Item",
        quantity=5,
        version_num=1,
        operation="CREATE",
        changed_by_id=mod_owner.id,
    )
    item_ver2 = ItemVersion(
        item_id=20,
        inventory_id=inv1.id,
        name="Deleted Item",
        quantity=5,
        version_num=2,
        operation="DELETE",
        changed_by_id=mod_owner.id,
    )

    # ItemVersion where parent inventory was also deleted (item_id = 30, inventory_id = 999)
    orphan_ver = ItemVersion(
        item_id=30,
        inventory_id=999,
        name="Orphan Item",
        quantity=1,
        version_num=1,
        operation="CREATE",
        changed_by_id=mod_owner.id,
    )

    db.add_all([item_ver1, item_ver2, orphan_ver])
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
        "state": state,
    }

    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def test_nonexistent_item_history_returns_404(auth_ctx):
    client = auth_ctx["client"]
    auth_ctx["state"]["user_id"] = auth_ctx["mod_other"].id

    # Item 99999 does not exist (no Item, no ItemVersion)
    res = client.get("/item/99999/history")
    assert res.status_code == 404
    assert res.json()["detail"] == "Item non trovato"


def test_unauthorized_user_cannot_view_active_or_deleted_item_history(auth_ctx):
    client = auth_ctx["client"]
    auth_ctx["state"]["user_id"] = auth_ctx["mod_other"].id

    # Active item in mod_owner's inventory
    res_active = client.get("/item/10/history")
    assert res_active.status_code == 403
    assert res_active.json()["detail"] == "Accesso negato"

    # Deleted item in mod_owner's inventory
    res_deleted = client.get("/item/20/history")
    assert res_deleted.status_code == 403
    assert res_deleted.json()["detail"] == "Accesso negato"


def test_authorized_owner_and_admin_can_view_deleted_item_history(auth_ctx):
    client = auth_ctx["client"]

    # Owner can view deleted item history
    auth_ctx["state"]["user_id"] = auth_ctx["mod_owner"].id
    res_owner = client.get("/item/20/history")
    assert res_owner.status_code == 200
    assert len(res_owner.json()) == 2
    assert res_owner.json()[0]["version_num"] == 1

    # Admin can also view deleted item history
    auth_ctx["state"]["user_id"] = auth_ctx["admin_user"].id
    res_admin = client.get("/item/20/history")
    assert res_admin.status_code == 200
    assert len(res_admin.json()) == 2


def test_orphan_deleted_item_accessible_only_by_admin(auth_ctx):
    client = auth_ctx["client"]

    # Non-admin cannot view orphan item history whose inventory was deleted
    auth_ctx["state"]["user_id"] = auth_ctx["mod_owner"].id
    res_owner = client.get("/item/30/history")
    assert res_owner.status_code == 403
    assert res_owner.json()["detail"] == "Accesso negato"

    # Admin can view orphan item history
    auth_ctx["state"]["user_id"] = auth_ctx["admin_user"].id
    res_admin = client.get("/item/30/history")
    assert res_admin.status_code == 200
    assert len(res_admin.json()) == 1
