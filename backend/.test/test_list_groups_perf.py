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
from models import User, Role, RoleEnum, Group, UserGroupAssociation, Setting
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
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    init_roles_and_admin(db)
    db.add(Setting(key="BACKUP_FREQUENCY", value="daily"))
    db.commit()
    db.close()
    yield
    app.dependency_overrides.clear()

client = TestClient(app)

def test_list_groups_query_count_is_constant(setup_db):
    """Verify that list_groups avoids N+1 queries when multiple groups and group users exist."""
    db = TestingSessionLocal()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()
    viewer_role = db.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    # Create 15 groups with 2 members each
    groups = []
    for g_idx in range(15):
        grp = Group(name=f"perf_group_{g_idx}", role_id=viewer_role.id)
        db.add(grp)
        groups.append(grp)
    db.commit()

    for idx, grp in enumerate(groups):
        u1 = User(username=f"g_{idx}_user_1", hashed_password=hash_password("pw"), role_id=mod_role.id)
        u2 = User(username=f"g_{idx}_user_2", hashed_password=hash_password("pw"), role_id=viewer_role.id)
        db.add(u1)
        db.add(u2)
        db.commit()
        db.add(UserGroupAssociation(user_id=u1.id, group_id=grp.id))
        db.add(UserGroupAssociation(user_id=u2.id, group_id=grp.id))
    db.commit()
    db.close()

    token = create_access_token({"sub": "admin"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            "/user/groups/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 15
        for item in data:
            assert len(item["users"]) == 2
            assert "role" in item
            assert item["role"]["name"] == "viewer"
            for member in item["users"]:
                assert "role" in member
                assert member["role"]["name"] in {"moderator", "viewer"}

        # Without joinedload, list_groups executes 1 query for auth + 1 for groups + 15 for group.users
        # + lazy queries for each user's role (30+) => 45+ queries total.
        # With joinedload, all groups, roles, users, and user roles are loaded in constant O(1) queries.
        assert len(queries) <= 5, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)

def test_list_users_query_count_is_constant(setup_db):
    """Verify that list_users avoids N+1 queries when multiple users across different roles exist."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()
    viewer_role = db.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    roles = [admin_role, mod_role, viewer_role]
    for i in range(15):
        u = User(username=f"perf_user_{i}", hashed_password=hash_password("pw"), role_id=roles[i % len(roles)].id)
        db.add(u)
    db.commit()
    db.close()

    token = create_access_token({"sub": "admin"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            "/user/users/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        # 1 default admin + 15 users = 16 users
        assert len(data) == 16
        for u in data:
            assert "role" in u
            assert u["role"]["name"] in {"admin", "moderator", "viewer"}

        # Constant queries (auth user + roles joined query)
        assert len(queries) <= 5, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
