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
from models import (
    User,
    Role,
    RoleEnum,
    Inventory,
    SharedInventory,
    SharedInventoryGroup,
    Group,
    Setting,
    ItemVersion,
    InventoryVersion,
)
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


def test_audit_logs_non_admin_query_count_is_constant(setup_db):
    """Verify that item and inventory audit log endpoints execute O(1) queries rather than O(N) queries for non-admins."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()

    admin_user = User(username="admin_owner", hashed_password=hash_password("pw"), role_id=admin_role.id)
    mod_user = User(username="mod_audit_tester", hashed_password=hash_password("pw"), role_id=mod_role.id)
    db.add_all([admin_user, mod_user])
    db.commit()

    # Create 15 inventories owned by admin
    inventories = []
    for i in range(15):
        inv = Inventory(name=f"Perf Inv {i}", owner_id=admin_user.id, type="INVENTORY")
        db.add(inv)
        inventories.append(inv)
    db.commit()

    # Share 5 directly with mod_user
    for inv in inventories[:5]:
        db.add(SharedInventory(inventory_id=inv.id, user_id=mod_user.id))

    # Share 5 through a group
    test_group = Group(name="perf_audit_group", role_id=mod_role.id)
    db.add(test_group)
    db.commit()
    test_group.users.append(mod_user)
    db.commit()

    for inv in inventories[5:10]:
        db.add(SharedInventoryGroup(inventory_id=inv.id, group_id=test_group.id))
    db.commit()

    # Create item version logs and inventory version logs
    for inv in inventories[:10]:
        db.add(
            ItemVersion(
                item_id=100 + inv.id,
                inventory_id=inv.id,
                name=f"Item in {inv.name}",
                quantity=1,
                version_num=1,
                operation="CREATE",
                changed_by_id=admin_user.id,
                changed_by_username=admin_user.username,
            )
        )
        db.add(
            InventoryVersion(
                inventory_id=inv.id,
                name=inv.name,
                type=inv.type,
                owner_id=inv.owner_id,
                version_num=1,
                operation="CREATE",
                changed_by_id=admin_user.id,
                changed_by_username=admin_user.username,
            )
        )
    db.commit()
    db.close()

    token = create_access_token({"sub": "mod_audit_tester"})

    # 1. Test /audit/logs/items
    queries = []

    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            "/audit/logs/items",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 10
        # Without joinedload on Inventory shares, checking 15 inventories causes 2 queries per inventory (35 queries total).
        # With joinedload, query count should remain constant (<= 7 queries total).
        assert len(queries) <= 7, f"Too many queries executed on /audit/logs/items: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)

    # 2. Test /audit/logs/inventories
    queries = []
    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            "/audit/logs/inventories",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 10
        # Without joinedload, checking 15 inventories causes 2 queries per inventory (35 queries total).
        # With joinedload, query count should remain constant (<= 6 queries total).
        assert len(queries) <= 6, f"Too many queries executed on /audit/logs/inventories: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
