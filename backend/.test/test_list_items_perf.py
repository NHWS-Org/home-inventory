import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["SECRET_KEY"] = "testsecretkey32byteslongforsecurity!"
os.environ["ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["ADMIN_PASSWORD"] = "adminpassword"

import dependencies
import routes.auth
dependencies.SECRET_KEY = "testsecretkey32byteslongforsecurity!"
dependencies.ALGORITHM = "HS256"
dependencies.ACCESS_TOKEN_EXPIRE_MINUTES = 30
routes.auth.SECRET_KEY = "testsecretkey32byteslongforsecurity!"
routes.auth.ALGORITHM = "HS256"
routes.auth.ACCESS_TOKEN_EXPIRE_MINUTES = 30

from main import app
from database import Base
from dependencies import get_db, init_roles_and_admin
from models import User, Role, RoleEnum, Inventory, Item, ListAssignment, Setting
from routes.auth import hash_password, create_access_token

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
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
    if not db.query(Setting).filter_by(key="BACKUP_FREQUENCY").first():
        db.add(Setting(key="BACKUP_FREQUENCY", value="daily"))
        db.commit()
    db.close()
    yield
    app.dependency_overrides.clear()

client = TestClient(app)

def test_list_inventory_items_query_count_is_constant(setup_db):
    """Verify that listing items in an inventory executes O(1) queries rather than N lazy queries for assignments."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    owner = User(username="owner_perf_test", hashed_password=hash_password("pw"), role_id=admin_role.id)
    db.add(owner)
    db.commit()

    inv = Inventory(name="Source Inventory", owner_id=owner.id, type="INVENTORY")
    chk = Inventory(name="Checklist Inventory", owner_id=owner.id, type="CHECKLIST")
    db.add_all([inv, chk])
    db.commit()

    # Create 20 items in the inventory
    inv_items = []
    for i in range(20):
        item = Item(name=f"Inventory Item {i}", quantity=10, inventory_id=inv.id, user_ins=owner.id)
        db.add(item)
        inv_items.append(item)
    db.commit()

    # Create 5 checklist items that assign to some of the inventory items
    for i in range(5):
        chk_item = Item(name=f"Chk Item {i}", quantity=0, inventory_id=chk.id, user_ins=owner.id)
        db.add(chk_item)
        db.flush()
        db.add(ListAssignment(list_item_id=chk_item.id, source_item_id=inv_items[i].id, qty=2))
    db.commit()

    inv_id = inv.id
    db.close()

    token = create_access_token({"sub": "owner_perf_test"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/inventory/item/{inv_id}/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 20

        # Verify that assignment counts and net quantities are accurately computed
        item_map = {it["name"]: it for it in data}
        for i in range(5):
            it = item_map[f"Inventory Item {i}"]
            assert it["assignment_count"] == 1
            assert it["assigned_qty"] == 2
            assert it["net_qty"] == 8

        for i in range(5, 20):
            it = item_map[f"Inventory Item {i}"]
            assert it["assignment_count"] == 0
            assert it["assigned_qty"] == 0

        # Without batching, each of the 20 items causes a lazy-load query for source_assignments (>= 24 queries total).
        # With batching, query count is O(1) regardless of item count (<= 6 queries).
        assert len(queries) <= 6, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)


def test_list_checklist_items_query_count_is_constant(setup_db):
    """Verify that listing items in a checklist executes O(1) queries rather than N queries for source items and inventories."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    owner = User(username="chk_perf_test", hashed_password=hash_password("pw"), role_id=admin_role.id)
    db.add(owner)
    db.commit()

    source_inv = Inventory(name="Source Warehouse", owner_id=owner.id, type="INVENTORY")
    checklist_inv = Inventory(name="Weekly Checklist", owner_id=owner.id, type="CHECKLIST")
    db.add_all([source_inv, checklist_inv])
    db.commit()

    source_items = []
    for i in range(20):
        src = Item(name=f"Supply {i}", quantity=15, inventory_id=source_inv.id, user_ins=owner.id)
        db.add(src)
        source_items.append(src)
    db.commit()

    for i in range(20):
        chk_item = Item(name=f"Checklist Item {i}", quantity=0, inventory_id=checklist_inv.id, user_ins=owner.id)
        db.add(chk_item)
        db.flush()
        db.add(ListAssignment(list_item_id=chk_item.id, source_item_id=source_items[i].id, qty=3))
    db.commit()

    chk_inv_id = checklist_inv.id
    db.close()

    token = create_access_token({"sub": "chk_perf_test"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/checklist/item/{chk_inv_id}/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 20

        # Verify that assignment summary details are properly loaded
        for item in data:
            assert item["assignment"] is not None
            assert item["assignment"]["source_inventory_name"] == "Source Warehouse"
            assert item["assignment"]["qty"] == 3
            assert item["assignment"]["source_stock"] == 15

        # Without eager loading of list_assignment.source_item and source_item.inventory,
        # each checklist item causes lazy queries (20 queries for source item + inventory lookups => > 25 queries).
        # With eager loading, query count should be <= 6.
        assert len(queries) <= 6, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
