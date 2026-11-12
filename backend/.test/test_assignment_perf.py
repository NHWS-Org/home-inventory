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

def test_list_assignments_by_source_query_count_is_constant(setup_db):
    """Verify that listing assignments by source item executes O(1) queries instead of O(N) queries."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    owner = User(username="assignment_perf_owner", hashed_password=hash_password("pw"), role_id=admin_role.id)
    db.add(owner)
    db.commit()

    source_inv = Inventory(name="Main Warehouse", owner_id=owner.id, type="INVENTORY")
    db.add(source_inv)
    db.commit()

    source_item = Item(name="Bulk Sugar", quantity=200, inventory_id=source_inv.id, user_ins=owner.id)
    db.add(source_item)
    db.commit()
    source_item_id = source_item.id

    # Create 15 checklist inventories with 1 item each assigning to source_item
    for i in range(15):
        chk = Inventory(name=f"Event Checklist {i}", owner_id=owner.id, type="CHECKLIST")
        db.add(chk)
        db.commit()
        chk_item = Item(name=f"Sugar Req {i}", quantity=0, inventory_id=chk.id, user_ins=owner.id)
        db.add(chk_item)
        db.flush()
        db.add(ListAssignment(list_item_id=chk_item.id, source_item_id=source_item_id, qty=3, user_ins=owner.id, user_mod=owner.id))
    db.commit()
    db.close()

    token = create_access_token({"sub": "assignment_perf_owner"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/assignment/by-source/{source_item_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 15

        # Check fields
        for entry in data:
            assert entry["source_item_id"] == source_item_id
            assert entry["source_name"] == "Bulk Sugar"
            assert entry["source_stock"] == 200
            # 15 * 3 = 45 pending assigned, 200 - 45 = 155 net
            assert entry["source_net_qty"] == 155
            assert entry["qty"] == 3

        # Without optimization:
        # - 1 query user auth
        # - 1 query user role
        # - 1 query source item (db.query(Item).get)
        # - 1 query Item.inventory
        # - 1 query Item.source_assignments
        # - 15 queries for each list_item
        # - 15 queries for each list_item.inventory
        # - 15 queries for pending_assigned_by_source in _source_net
        # Total queries without optimization would be > 45!
        #
        # With joinedload and batching pending calculation:
        # Query count is constant O(1) (<= 6 queries total).
        assert len(queries) <= 6, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
