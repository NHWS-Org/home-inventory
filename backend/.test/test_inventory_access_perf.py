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
from models import User, Role, RoleEnum, Inventory, Group, SharedInventory, SharedInventoryGroup, UserGroupAssociation, Setting
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

def _seed_test_inventory_with_shares(prefix="test"):
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()
    viewer_role = db.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    owner_name = f"{prefix}_owner_perf"
    owner = User(username=owner_name, hashed_password=hash_password("pw"), role_id=admin_role.id)
    extra_admin = User(username=f"{prefix}_extra_admin_perf", hashed_password=hash_password("pw"), role_id=admin_role.id)
    db.add_all([owner, extra_admin])
    db.commit()

    inv = Inventory(name=f"{prefix} Perf Access Inventory", owner_id=owner.id, type="INVENTORY")
    db.add(inv)
    db.commit()
    inv_id = inv.id

    # 10 direct shares
    for i in range(10):
        u = User(username=f"{prefix}_direct_share_user_{i}", hashed_password=hash_password("pw"), role_id=mod_role.id)
        db.add(u)
        db.commit()
        db.add(SharedInventory(inventory_id=inv_id, user_id=u.id))
    db.commit()

    # 5 groups with 4 users each (20 group users total)
    for g_idx in range(5):
        grp = Group(name=f"{prefix}_Access_Group_{g_idx}", role_id=viewer_role.id)
        db.add(grp)
        db.commit()
        db.add(SharedInventoryGroup(inventory_id=inv_id, group_id=grp.id))
        for u_idx in range(4):
            gu = User(username=f"{prefix}_grp_{g_idx}_user_{u_idx}", hashed_password=hash_password("pw"), role_id=viewer_role.id)
            db.add(gu)
            db.commit()
            db.add(UserGroupAssociation(user_id=gu.id, group_id=grp.id))
    db.commit()
    db.close()
    return inv_id, owner_name

def test_list_access_details_query_count_is_constant(setup_db):
    """Verify that listing inventory access details executes O(1) queries instead of O(N_shares + N_groups) queries."""
    inv_id, owner_name = _seed_test_inventory_with_shares("details")
    token = create_access_token({"sub": owner_name})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/inventory/access_details/{inv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()

        # 1 owner + 2 admins (default admin + extra admin) + 10 direct shares + 20 group members = 33 entries
        assert len(data) >= 32

        # Verify entry details
        vias = {entry["via"] for entry in data}
        assert vias == {"owner", "admin", "share", "group"}

        # Without joinedload, query count would be > 40:
        # - 1 current user
        # - 1 inventory lookup
        # - 1 owner User lookup
        # - 1 admin Users lookup
        # - 10 direct share User lookups + lazy role lookups
        # - 5 group lookups + 5 group association lookups + 20 user lookups + lazy role lookups
        # With joinedload, query count is O(1) (auth + inventory with joined relations + admins).
        assert len(queries) <= 6, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)


def test_count_access_by_type_query_count_is_constant(setup_db):
    """Verify that counting inventory access by type executes O(1) queries instead of O(N) queries."""
    inv_id, owner_name = _seed_test_inventory_with_shares("count")
    token = create_access_token({"sub": owner_name})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/inventory/access_count/{inv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["admin"] >= 1   # extra admin (+ default admin)
        assert data["edit"] == 11   # owner + 10 mod direct shares
        assert data["view"] == 20   # 20 group members

        assert len(queries) <= 6, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)


def test_list_group_shares_query_count_is_constant(setup_db):
    """Verify that listing group shares executes O(1) queries instead of N queries for group names."""
    inv_id, owner_name = _seed_test_inventory_with_shares("groups")
    token = create_access_token({"sub": owner_name})

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
        assert len(data) == 5
        assert set(data) == {f"groups_Access_Group_{i}" for i in range(5)}

        assert len(queries) <= 5, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
