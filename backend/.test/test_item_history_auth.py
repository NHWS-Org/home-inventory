import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base
from dependencies import get_db
from models import User, Role, Inventory, Item, ItemVersion, SharedInventory
from routes.auth import get_current_user


@pytest.fixture
def auth_ctx():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add_all([Role(id=1, name="admin"), Role(id=2, name="moderator"), Role(id=3, name="viewer")])
        db.flush()
        db.add_all([
            User(id=1, username="admin", role_id=1),
            User(id=2, username="owner", role_id=2),
            User(id=3, username="other", role_id=2),
            User(id=4, username="viewer", role_id=3),
            User(id=5, username="shared_viewer", role_id=3),
        ])
        db.flush()
        db.add(Inventory(id=1, name="Owner inventory", owner_id=2, type="INVENTORY"))
        db.flush()
        db.add(SharedInventory(user_id=5, inventory_id=1))
        db.add(Item(id=10, name="Active", inventory_id=1, quantity=5))
        db.add_all([
            ItemVersion(item_id=10, inventory_id=1, name="Active", quantity=5,
                        version_num=1, operation="CREATE", changed_by_id=2),
            ItemVersion(item_id=20, inventory_id=1, name="Deleted", quantity=5,
                        version_num=1, operation="CREATE", changed_by_id=2),
            ItemVersion(item_id=20, inventory_id=1, name="Deleted", quantity=5,
                        version_num=2, operation="DELETE", changed_by_id=2),
            ItemVersion(item_id=30, inventory_id=999, name="Orphan", quantity=1,
                        version_num=1, operation="CREATE", changed_by_id=2),
        ])
    current = [2]

    def database():
        with factory() as db:
            yield db

    def user():
        with factory() as db:
            row = db.get(User, current[0])
            row.role
            row.group_associations
            return row

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = user
    try:
        yield TestClient(app), current
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


@pytest.mark.parametrize("user_id", [1, 2, 3, 4, 5])
def test_nonexistent_item_history_returns_404(auth_ctx, user_id):
    client, current = auth_ctx
    current[0] = user_id
    response = client.get("/item/99999/history")
    assert response.status_code == 404
    assert response.json()["detail"] == "Item non trovato"


@pytest.mark.parametrize("user_id,item_id,status,count", [
    (1, 10, 200, 1), (2, 10, 200, 1), (3, 10, 403, 0),
    (4, 10, 403, 0), (5, 10, 200, 1),
    (1, 20, 200, 2), (2, 20, 200, 2), (3, 20, 403, 0),
    (4, 20, 403, 0), (5, 20, 403, 0),
    (1, 30, 200, 1), (2, 30, 403, 0), (3, 30, 403, 0),
    (4, 30, 403, 0), (5, 30, 403, 0),
])
def test_history_access_for_active_deleted_and_orphan_items(auth_ctx, user_id, item_id, status, count):
    client, current = auth_ctx
    current[0] = user_id
    response = client.get(f"/item/{item_id}/history")
    assert response.status_code == status
    if status == 200:
        assert len(response.json()) == count
        assert response.json()[0]["version_num"] == 1
    else:
        assert response.json()["detail"] == "Accesso negato"
