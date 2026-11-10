import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base
from dependencies import get_db
from models import User, Role, RoleEnum, Inventory, Item, ItemVersion, SharedInventory
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
    viewer_shared = User(username="viewer_shared", hashed_password="x", role_id=viewer_role.id)
    db.add_all([admin_user, mod_owner, mod_other, viewer_user, viewer_shared])
    db.commit()

    # Active inventory owned by mod_owner
    inv1 = Inventory(name="Owner Inv", type="INVENTORY", owner_id=mod_owner.id, user_ins=mod_owner.id)
    # Another inventory not accessible to viewer_user or mod_other
    inv2 = Inventory(name="Other Inv", type="INVENTORY", owner_id=mod_other.id, user_ins=mod_other.id)
    db.add_all([inv1, inv2])
    db.commit()

    # Share inv1 with viewer_shared
    shared = SharedInventory(user_id=viewer_shared.id, inventory_id=inv1.id)
    db.add(shared)
    db.commit()

    # Live item in inv1
    item_live = Item(id=1, name="Live Item", quantity=5, inventory_id=inv1.id, user_ins=mod_owner.id)
    # Live item in inv2
    item_other = Item(id=2, name="Other Item", quantity=2, inventory_id=inv2.id, user_ins=mod_other.id)
    db.add_all([item_live, item_other])
    db.commit()

    # Versions for live item 1
    ver_live = ItemVersion(
        item_id=1,
        inventory_id=inv1.id,
        name="Live Item",
        quantity=5,
        version_num=1,
        operation="CREATE",
        changed_by_id=mod_owner.id,
    )

    # Deleted item history: item_id = 100, formerly in inv1 (no live item row in items table)
    ver_del1 = ItemVersion(
        item_id=100,
        inventory_id=inv1.id,
        name="Deleted Item",
        quantity=10,
        version_num=1,
        operation="CREATE",
        changed_by_id=mod_owner.id,
    )
    ver_del2 = ItemVersion(
        item_id=100,
        inventory_id=inv1.id,
        name="Deleted Item",
        quantity=0,
        version_num=2,
        operation="DELETE",
        changed_by_id=mod_owner.id,
    )

    db.add_all([ver_live, ver_del1, ver_del2])
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
        "viewer_shared": viewer_shared,
        "state": state,
    }

    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def test_nonexistent_item_history_returns_404(auth_ctx):
    client = auth_ctx["client"]
    auth_ctx["state"]["user_id"] = auth_ctx["mod_owner"].id

    res = client.get("/item/9999/history")
    assert res.status_code == 404
    assert res.json()["detail"] == "Item non trovato"


def test_live_item_history_unauthorized_user_forbidden(auth_ctx):
    client = auth_ctx["client"]
    # mod_other cannot view item 1 in inv1
    auth_ctx["state"]["user_id"] = auth_ctx["mod_other"].id

    res = client.get("/item/1/history")
    assert res.status_code == 403
    assert res.json()["detail"] == "Accesso negato"


def test_deleted_item_history_unauthorized_user_forbidden(auth_ctx):
    client = auth_ctx["client"]
    # mod_other cannot view deleted item 100 from inv1
    auth_ctx["state"]["user_id"] = auth_ctx["mod_other"].id

    res = client.get("/item/100/history")
    assert res.status_code == 403
    assert res.json()["detail"] == "Accesso negato"


def test_deleted_item_history_viewer_forbidden(auth_ctx):
    client = auth_ctx["client"]
    # viewer_shared has view access to inv1, but viewers cannot access deleted entity history
    auth_ctx["state"]["user_id"] = auth_ctx["viewer_shared"].id

    res = client.get("/item/100/history")
    assert res.status_code == 403
    assert res.json()["detail"] == "Accesso negato"


def test_authorized_users_can_access_live_and_deleted_item_history(auth_ctx):
    client = auth_ctx["client"]

    # mod_owner can view live item history
    auth_ctx["state"]["user_id"] = auth_ctx["mod_owner"].id
    res_live = client.get("/item/1/history")
    assert res_live.status_code == 200
    assert len(res_live.json()) == 1

    # viewer_shared can view live item history in shared inv1
    auth_ctx["state"]["user_id"] = auth_ctx["viewer_shared"].id
    res_live_viewer = client.get("/item/1/history")
    assert res_live_viewer.status_code == 200
    assert len(res_live_viewer.json()) == 1

    # mod_owner can view deleted item history
    auth_ctx["state"]["user_id"] = auth_ctx["mod_owner"].id
    res_del_owner = client.get("/item/100/history")
    assert res_del_owner.status_code == 200
    assert len(res_del_owner.json()) == 2

    # admin can view deleted item history
    auth_ctx["state"]["user_id"] = auth_ctx["admin_user"].id
    res_del_admin = client.get("/item/100/history")
    assert res_del_admin.status_code == 200
    assert len(res_del_admin.json()) == 2
