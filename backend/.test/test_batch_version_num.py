import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base
from dependencies import get_db, init_roles_and_admin
from sqlalchemy import event
from models import User, Role, RoleEnum, Inventory, Item, ItemVersion, InventoryVersion
from routes.auth import hash_password, create_access_token

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    init_roles_and_admin(db)
    db.close()
    yield
    app.dependency_overrides.clear()

client = TestClient(app)

def test_list_inventories_batch_version_num(setup_db):
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    admin_user = User(
        username="admin_batch_test",
        hashed_password=hash_password("adminpassword"),
        role_id=admin_role.id
    )
    db.add(admin_user)
    db.commit()

    inv = Inventory(name="Batch Test Inventory", owner_id=admin_user.id, type="INVENTORY")
    db.add(inv)
    db.commit()
    inv_id = inv.id

    item1 = Item(name="Item 1", quantity=10, inventory_id=inv_id, user_ins=admin_user.id)
    item2 = Item(name="Item 2", quantity=20, inventory_id=inv_id, user_ins=admin_user.id)
    db.add(item1)
    db.add(item2)
    db.commit()

    v1 = ItemVersion(
        item_id=item1.id,
        inventory_id=inv_id,
        name="Item 1",
        quantity=10,
        version_num=3,
        operation="CREATE",
        changed_by_id=admin_user.id
    )
    v2 = ItemVersion(
        item_id=item2.id,
        inventory_id=inv_id,
        name="Item 2",
        quantity=20,
        version_num=5,
        operation="CREATE",
        changed_by_id=admin_user.id
    )
    db.add(v1)
    db.add(v2)
    db.commit()
    db.close()

    token = create_access_token({"sub": "admin_batch_test"})
    res = client.get(
        "/inventory/",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1

    res_items = client.get(
        f"/inventory/item/{inv_id}/",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_items.status_code == 200
    items_data = res_items.json()
    items_map = {item["name"]: item["version_num"] for item in items_data}
    assert items_map["Item 1"] == 3
    assert items_map["Item 2"] == 5


def test_list_inventories_batch_version_query_efficiency(setup_db):
    """Verify that listing multiple inventories batches InventoryVersion queries rather than executing N queries."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    admin_user = User(
        username="admin_perf_test",
        hashed_password=hash_password("adminpassword"),
        role_id=admin_role.id
    )
    db.add(admin_user)
    db.commit()

    # Create 5 inventories with versions
    for i in range(5):
        inv = Inventory(name=f"Perf Inventory {i}", owner_id=admin_user.id, type="INVENTORY")
        db.add(inv)
        db.commit()

        v = InventoryVersion(
            inventory_id=inv.id,
            name=inv.name,
            type=inv.type,
            owner_id=admin_user.id,
            version_num=i + 1,
            operation="CREATE",
            changed_by_id=admin_user.id
        )
        db.add(v)
    db.commit()
    db.close()

    token = create_access_token({"sub": "admin_perf_test"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            "/inventory/",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 5

        # Check that version numbers are correctly populated from the batch fetch
        version_by_name = {inv["name"]: inv["version_num"] for inv in data if inv["name"].startswith("Perf Inventory ")}
        for i in range(5):
            assert version_by_name[f"Perf Inventory {i}"] == i + 1

        # Check how many queries touched inventory_versions
        inv_version_queries = [
            q for q in queries
            if "inventory_versions" in q.lower() or "inventoryversion" in q.lower()
        ]
        # Should be exactly 1 batched query for inventory versions, NOT 5 (or more) individual queries
        assert len(inv_version_queries) == 1, (
            f"Expected 1 batched query for inventory versions, found {len(inv_version_queries)}: {inv_version_queries}"
        )
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
