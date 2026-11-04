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
from models import User, Role, RoleEnum, Inventory, Group, SharedInventoryGroup, UserGroupAssociation
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

def test_get_shareable_users_query_count_is_constant(setup_db):
    """Verify that get_shareable_users avoids N+1 queries when multiple shared groups and users exist."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()
    viewer_role = db.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    owner = User(username="owner_user", hashed_password=hash_password("pw"), role_id=admin_role.id)
    db.add(owner)
    db.commit()

    inv = Inventory(name="Inventory for shareable", owner_id=owner.id, type="INVENTORY")
    db.add(inv)
    db.commit()
    inv_id = inv.id

    # Create 5 groups and associate them with the inventory
    groups = []
    for g_idx in range(5):
        grp = Group(name=f"Group_{g_idx}", role_id=viewer_role.id)
        db.add(grp)
        groups.append(grp)
    db.commit()

    for grp in groups:
        db.add(SharedInventoryGroup(inventory_id=inv_id, group_id=grp.id))
    db.commit()

    # Create 10 users in groups (already shared)
    for i in range(10):
        u = User(username=f"grouped_user_{i}", hashed_password=hash_password("pw"), role_id=viewer_role.id)
        db.add(u)
        db.commit()
        db.add(UserGroupAssociation(user_id=u.id, group_id=groups[i % len(groups)].id))
    db.commit()

    # Create 15 non-admin shareable users
    for i in range(15):
        u = User(username=f"shareable_user_{i}", hashed_password=hash_password("pw"), role_id=mod_role.id)
        db.add(u)
    db.commit()
    db.close()

    token = create_access_token({"sub": "owner_user"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/user/users/shareable/{inv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        # Verify 15 shareable users returned and grouped/admin users excluded
        assert len(data) == 15
        usernames = {u["username"] for u in data}
        assert all(f"shareable_user_{i}" in usernames for i in range(15))
        assert not any("grouped_user" in u["username"] for u in data)

        # In un-optimized code:
        # - 1 query for current_user
        # - 1 query for inventory + joined loads
        # - 5 queries for Group lookups (1 per shared_with_groups)
        # - 5 queries lazy loading group.users
        # - 1 query for all non-admin users
        # - 15 queries lazy-loading role for each user in UserResponse serialization
        # Total: ~28+ queries!
        # With Bolt optimization:
        # - 1 query current_user
        # - 1 query inventory + joined shares
        # - 1 query UserGroupAssociation where group_id IN (...)
        # - 1 query non-admin users with joinedload(User.role)
        # Total should be <= 6 queries.
        assert len(queries) <= 6, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
