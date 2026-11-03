import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base
from dependencies import get_db
from models import User, Role, RoleEnum, Inventory, Item, SharedInventory
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

    inv1 = Inventory(name="Inv 1", type="INVENTORY", owner_id=user1.id, user_ins=user1.id)
    inv2 = Inventory(name="Inv 2", type="INVENTORY", owner_id=user2.id, user_ins=user2.id)
    db.add_all([inv1, inv2])
    db.commit()

    item = Item(name="Test Item", quantity=5, inventory_id=inv1.id, user_ins=user1.id)
    db.add(item)
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
        "inv1": inv1,
        "inv2": inv2,
        "item": item,
        "state": state,
    }

    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def test_update_item_inventory_destination_authorization(auth_ctx):
    client = auth_ctx["client"]
    item = auth_ctx["item"]
    inv2 = auth_ctx["inv2"]
    user1 = auth_ctx["user1"]
    db = auth_ctx["db"]

    # 1. User1 attempts to move item to inv2 (unauthorized destination) -> 403 Forbidden
    res_forbidden = client.patch(
        f"/item/{item.id}",
        json={"name": "Test Item", "description": None, "quantity": 5, "inventory_id": inv2.id},
    )
    assert res_forbidden.status_code == 403
    assert "Accesso negato all'inventario di destinazione" in res_forbidden.json()["detail"]

    # 2. User1 attempts to move item to a non-existent inventory -> 404 Not Found
    res_not_found = client.patch(
        f"/item/{item.id}",
        json={"name": "Test Item", "description": None, "quantity": 5, "inventory_id": 999999},
    )
    assert res_not_found.status_code == 404
    assert "Inventario di destinazione non trovato" in res_not_found.json()["detail"]

    # 3. Share inv2 with user1 so user1 has edit rights on both inventories
    shared = SharedInventory(user_id=user1.id, inventory_id=inv2.id)
    db.add(shared)
    db.commit()

    # Now moving should succeed -> 200 OK
    res_success = client.patch(
        f"/item/{item.id}",
        json={"name": "Test Item", "description": None, "quantity": 5, "inventory_id": inv2.id},
    )
    assert res_success.status_code == 200
    assert res_success.json()["inventory_id"] == inv2.id

    # Verify target inventory timestamps were updated
    db.refresh(inv2)
    assert inv2.user_mod == user1.id
