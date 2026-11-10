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
from models import User, Role, RoleEnum, Inventory, SharedInventory, SharedInventoryGroup, Group, UserGroupAssociation
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
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    init_roles_and_admin(db)
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous_overrides)

client = TestClient(app)

@pytest.mark.parametrize("inventory_type", ["INVENTORY", "CHECKLIST"])
def test_list_access_details_query_count_is_constant(setup_db, inventory_type):
    """Verify that listing inventory access details executes O(1) queries rather than O(U + G*M) queries."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()
    viewer_role = db.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    owner = User(username="owner_user", hashed_password=hash_password("pw"), role_id=admin_role.id)
    db.add(owner)
    db.commit()

    inv = Inventory(name="Access Test Inventory", owner_id=owner.id, type=inventory_type)
    db.add(inv)
    db.commit()
    inv_id = inv.id

    # Create 10 directly shared users (5 mod, 5 viewer)
    shared_users = []
    for i in range(10):
        role_id = mod_role.id if i % 2 == 0 else viewer_role.id
        u = User(username=f"direct_user_{i}", hashed_password=hash_password("pw"), role_id=role_id)
        db.add(u)
        shared_users.append(u)
    db.commit()

    for u in shared_users:
        db.add(SharedInventory(inventory_id=inv_id, user_id=u.id))
    db.commit()

    # Create 3 groups, each with 3 users
    for g_idx in range(3):
        group = Group(name=f"access_group_{g_idx}", role_id=viewer_role.id)
        db.add(group)
        db.commit()
        db.add(SharedInventoryGroup(inventory_id=inv_id, group_id=group.id))
        db.commit()

        for u_idx in range(3):
            role_id = mod_role.id if u_idx == 0 else viewer_role.id
            gu = User(username=f"group_user_{g_idx}_{u_idx}", hashed_password=hash_password("pw"), role_id=role_id)
            db.add(gu)
            db.commit()
            db.add(UserGroupAssociation(user_id=gu.id, group_id=group.id))
            db.commit()

    db.close()

    token = create_access_token({"sub": "owner_user"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/{inventory_type.lower()}/access_details/{inv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()

        # Expected counts:
        # 1 owner
        # 1 other admin (ADMIN default user created by init_roles_and_admin)
        # 10 direct shares
        # 9 group shares (3 groups * 3 users)
        # Total = 21 entries
        assert len(data) == 21

        # Check owner entry
        owner_entries = [d for d in data if d["via"] == "owner"]
        assert len(owner_entries) == 1
        assert owner_entries[0]["username"] == "owner_user"
        assert owner_entries[0]["access"] == "edit"

        # Check direct share entries
        direct_entries = [d for d in data if d["via"] == "share"]
        assert len(direct_entries) == 10
        assert [(d["username"], d["access"]) for d in direct_entries] == [
            (f"direct_user_{i}", "edit" if i % 2 == 0 else "view")
            for i in range(10)
        ]

        # Check group entries
        group_entries = [d for d in data if d["via"] == "group"]
        assert len(group_entries) == 9
        assert [(d["username"], d["access"], d["group"]) for d in group_entries] == [
            (
                f"group_user_{g_idx}_{u_idx}",
                "edit" if u_idx == 0 else "view",
                f"access_group_{g_idx}",
            )
            for g_idx in range(3)
            for u_idx in range(3)
        ]

        # Without batching, query count would be > 30 queries:
        # auth (1) + inventory (1) + owner lookup (1) + admins (1) +
        # 10 direct users (10 * 2) + 3 groups (3) + 9 group users (9 * 2) => > 35 queries.
        # With batched/joined queries, query count is O(1) regardless of number of shares (<= 6 queries).
        assert len(queries) <= 6, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
