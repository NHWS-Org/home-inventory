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
from models import User, Role, RoleEnum, Inventory, SharedInventoryGroup, Group
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
    db.close()
    yield
    app.dependency_overrides.clear()

client = TestClient(app)

def test_list_inventory_group_shares_query_count_is_constant(setup_db):
    """Verify that listing inventory group shares does not execute N+1 queries as number of shared groups grows."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()

    owner = User(username="owner_user", hashed_password=hash_password("pw"), role_id=admin_role.id)
    db.add(owner)
    db.commit()

    inv = Inventory(name="Shared Inventory", owner_id=owner.id, type="INVENTORY")
    db.add(inv)
    db.commit()
    inv_id = inv.id

    # Create 15 shared groups
    groups = []
    for i in range(15):
        g = Group(name=f"shared_group_{i}", role_id=admin_role.id)
        db.add(g)
        groups.append(g)
    db.commit()

    for g in groups:
        db.add(SharedInventoryGroup(inventory_id=inv_id, group_id=g.id))
    db.commit()
    db.close()

    token = create_access_token({"sub": "owner_user"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/inventory/share_group/{inv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 15
        assert data == [f"shared_group_{i}" for i in range(15)]

        # If N+1 were present, query count would be >= 18 (auth + inventory + 15 lazy Group queries).
        # With optimization, query count is O(1) (auth + inventory lookup + 1 joined Group query => <= 5).
        assert len(queries) <= 5, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)


def test_list_checklist_group_shares_query_count_is_constant(setup_db):
    """Verify that listing checklist group shares also executes O(1) queries."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()

    owner = User(username="chk_owner_user", hashed_password=hash_password("pw"), role_id=admin_role.id)
    db.add(owner)
    db.commit()

    chk = Inventory(name="Shared Checklist", owner_id=owner.id, type="CHECKLIST")
    db.add(chk)
    db.commit()
    chk_id = chk.id

    # Create 10 shared groups
    groups = []
    for i in range(10):
        g = Group(name=f"chk_group_{i}", role_id=admin_role.id)
        db.add(g)
        groups.append(g)
    db.commit()

    for g in groups:
        db.add(SharedInventoryGroup(inventory_id=chk_id, group_id=g.id))
    db.commit()
    db.close()

    token = create_access_token({"sub": "chk_owner_user"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/checklist/share_group/{chk_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 10
        assert data == [f"chk_group_{i}" for i in range(10)]

        assert len(queries) <= 5, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
