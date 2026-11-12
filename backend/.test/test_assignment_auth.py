import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base
from dependencies import get_db
from models import User, Role, RoleEnum, Inventory, Item, ListAssignment, SharedInventory
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

    mod_role = Role(name=RoleEnum.moderator.value)
    db.add(mod_role)
    db.commit()

    user1 = User(username="user1", hashed_password="x", role_id=mod_role.id)
    user2 = User(username="user2", hashed_password="x", role_id=mod_role.id)
    db.add_all([user1, user2])
    db.commit()

    # user1 owns checklist; user2 owns source inventory
    checklist = Inventory(name="Checklist 1", type="CHECKLIST", owner_id=user1.id, user_ins=user1.id)
    source_inv = Inventory(name="Source Inv", type="INVENTORY", owner_id=user2.id, user_ins=user2.id)
    db.add_all([checklist, source_inv])
    db.commit()

    list_item = Item(name="Need Milk", quantity=0, inventory_id=checklist.id, user_ins=user1.id)
    source_item = Item(name="Milk Stock", quantity=10, inventory_id=source_inv.id, user_ins=user2.id)
    db.add_all([list_item, source_item])
    db.commit()

    assignment = ListAssignment(
        list_item_id=list_item.id,
        source_item_id=source_item.id,
        qty=2,
        user_ins=user2.id,
        user_mod=user2.id,
    )
    db.add(assignment)
    db.commit()

    state = {"user_id": user1.id}

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
        "user1": user1,
        "user2": user2,
        "checklist": checklist,
        "source_inv": source_inv,
        "list_item": list_item,
        "source_item": source_item,
        "assignment": assignment,
        "state": state,
    }

    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def test_assignment_source_authorization_enforced_on_patch_and_delete(auth_ctx):
    client = auth_ctx["client"]
    assignment = auth_ctx["assignment"]
    user1 = auth_ctx["user1"]
    source_inv = auth_ctx["source_inv"]
    db = auth_ctx["db"]

    # user1 owns checklist and can edit list_item, but has NO view access to source_inv
    # 1. PATCH assignment must return 403 Forbidden
    patch_forbidden = client.patch(
        f"/assignment/{assignment.id}",
        json={"qty": 4},
    )
    assert patch_forbidden.status_code == 403
    assert "Accesso negato" in patch_forbidden.json()["detail"]

    # 2. DELETE assignment must return 403 Forbidden
    delete_forbidden = client.delete(f"/assignment/{assignment.id}")
    assert delete_forbidden.status_code == 403
    assert "Accesso negato" in delete_forbidden.json()["detail"]

    # 3. Share source_inv with user1 so user1 can view source_item
    shared = SharedInventory(user_id=user1.id, inventory_id=source_inv.id)
    db.add(shared)
    db.commit()

    # Now PATCH should succeed
    patch_ok = client.patch(
        f"/assignment/{assignment.id}",
        json={"qty": 4},
    )
    assert patch_ok.status_code == 200
    assert patch_ok.json()["qty"] == 4

    # And DELETE should succeed
    delete_ok = client.delete(f"/assignment/{assignment.id}")
    assert delete_ok.status_code == 200
    assert delete_ok.json() == {"detail": "Assegnazione eliminata"}


@pytest.mark.parametrize("checked", [False, True])
def test_assignments_by_source_filters_hidden_lists_and_keeps_stock_totals(auth_ctx, checked):
    db = auth_ctx["db"]
    source = auth_ctx["source_item"]
    auth_ctx["state"]["user_id"] = auth_ctx["user1"].id
    url = f"/assignment/by-source/{source.id}"
    assert auth_ctx["client"].get(url).status_code == 403

    db.add(SharedInventory(user_id=auth_ctx["user1"].id, inventory_id=auth_ctx["source_inv"].id))
    hidden_list = Inventory(name="Hidden", type="CHECKLIST", owner_id=auth_ctx["user2"].id)
    db.add(hidden_list)
    db.flush()
    hidden_item = Item(name="Private row", quantity=0, inventory_id=hidden_list.id)
    db.add(hidden_item)
    db.flush()
    db.add(ListAssignment(
        list_item_id=hidden_item.id, source_item_id=source.id, qty=3,
        user_ins=auth_ctx["user2"].id, user_mod=auth_ctx["user2"].id,
    ))
    auth_ctx["list_item"].quantity = int(checked)
    db.commit()

    response = auth_ctx["client"].get(url)
    assert response.status_code == 200
    [visible] = response.json()
    assert visible["id"] == auth_ctx["assignment"].id
    assert visible["list_checked"] is checked
    assert visible["source_stock"] == 10
    assert visible["source_net_qty"] == (7 if checked else 5)
