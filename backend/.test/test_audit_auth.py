import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
from dependencies import get_db, init_roles_and_admin, initialize_settings
from models import User, Role, RoleEnum, Inventory, Item, ItemVersion, InventoryVersion, SharedInventory, Group, SharedInventoryGroup
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
def db_session():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    init_roles_and_admin(db)
    initialize_settings(db)
    yield db
    db.close()
    app.dependency_overrides.clear()

client = TestClient(app)

def test_item_audit_logs_authorization(db_session):
    viewer_role = db_session.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    # User 1 (owner of inv1)
    user1 = User(
        username="audit_owner",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    # User 2 (shared user on inv1, owner of inv2)
    user2 = User(
        username="audit_shared",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    # User 3 (unauthorized user)
    user3 = User(
        username="audit_unauthorized",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    db_session.add_all([user1, user2, user3])
    db_session.commit()

    # Inventories
    inv1 = Inventory(name="Owner Inv 1", owner_id=user1.id, type="INVENTORY")
    inv2 = Inventory(name="Owner Inv 2", owner_id=user2.id, type="INVENTORY")
    inv_secret = Inventory(name="Secret Inv", owner_id=user1.id, type="INVENTORY")
    db_session.add_all([inv1, inv2, inv_secret])
    db_session.commit()

    # Share inv1 directly with user2
    db_session.add(SharedInventory(user_id=user2.id, inventory_id=inv1.id))

    # Share inv2 via group with user1
    group = Group(name="Audit Group", role_id=viewer_role.id)
    db_session.add(group)
    db_session.commit()
    group.users.append(user1)
    db_session.add(SharedInventoryGroup(group_id=group.id, inventory_id=inv2.id))
    db_session.commit()

    # Create items and item audit logs
    log1 = ItemVersion(
        item_id=101,
        inventory_id=inv1.id,
        name="Item in Inv 1",
        quantity=5,
        version_num=1,
        operation="CREATE",
        changed_by_id=user1.id,
        changed_by_username=user1.username
    )
    log2 = ItemVersion(
        item_id=102,
        inventory_id=inv2.id,
        name="Item in Inv 2",
        quantity=10,
        version_num=1,
        operation="CREATE",
        changed_by_id=user2.id,
        changed_by_username=user2.username
    )
    log_secret = ItemVersion(
        item_id=103,
        inventory_id=inv_secret.id,
        name="Item in Secret Inv",
        quantity=1,
        version_num=1,
        operation="CREATE",
        changed_by_id=user1.id,
        changed_by_username=user1.username
    )
    db_session.add_all([log1, log2, log_secret])
    db_session.commit()

    token1 = create_access_token({"sub": "audit_owner"})
    token2 = create_access_token({"sub": "audit_shared"})
    token3 = create_access_token({"sub": "audit_unauthorized"})

    # 1. User 1 (owns inv1 & inv_secret, group member on inv2) lists logs -> sees log1, log2, log_secret
    res1 = client.get("/audit/logs/items", headers={"Authorization": f"Bearer {token1}"})
    assert res1.status_code == 200
    ids1 = [item["item_id"] for item in res1.json()]
    assert 101 in ids1
    assert 102 in ids1
    assert 103 in ids1

    # 2. User 2 (owns inv2, directly shared on inv1) lists logs -> sees log1 and log2, but NOT log_secret
    res2 = client.get("/audit/logs/items", headers={"Authorization": f"Bearer {token2}"})
    assert res2.status_code == 200
    ids2 = [item["item_id"] for item in res2.json()]
    assert 101 in ids2
    assert 102 in ids2
    assert 103 not in ids2

    # 3. User 2 queries specific shared inventory (inv1) -> sees log1
    res2_inv1 = client.get(f"/audit/logs/items?inventory_id={inv1.id}", headers={"Authorization": f"Bearer {token2}"})
    assert res2_inv1.status_code == 200
    ids2_inv1 = [item["item_id"] for item in res2_inv1.json()]
    assert 101 in ids2_inv1

    # 4. User 3 (unauthorized) lists logs -> sees empty list []
    res3 = client.get("/audit/logs/items", headers={"Authorization": f"Bearer {token3}"})
    assert res3.status_code == 200
    assert len(res3.json()) == 0

    # 5. User 3 queries unauthorized inventory (inv1) -> sees empty list []
    res3_inv1 = client.get(f"/audit/logs/items?inventory_id={inv1.id}", headers={"Authorization": f"Bearer {token3}"})
    assert res3_inv1.status_code == 200
    assert len(res3_inv1.json()) == 0

    # 6. Admin user lists logs -> sees all logs (101, 102, 103)
    login_admin = client.post("/auth/login", data={"username": "admin", "password": "adminpassword"})
    admin_token = login_admin.json()["access_token"]
    admin_res = client.get("/audit/logs/items", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_res.status_code == 200
    admin_ids = [item["item_id"] for item in admin_res.json()]
    assert 101 in admin_ids
    assert 102 in admin_ids
    assert 103 in admin_ids


def test_inventory_audit_logs_authorization(db_session):
    viewer_role = db_session.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    # User 1 (owner of inv1)
    user1 = User(
        username="inv_audit_owner",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    # User 2 (shared user on inv1, owner of inv2)
    user2 = User(
        username="inv_audit_shared",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    # User 3 (unauthorized user)
    user3 = User(
        username="inv_audit_unauthorized",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    db_session.add_all([user1, user2, user3])
    db_session.commit()

    # Inventories
    inv1 = Inventory(name="Audit Inv 1", owner_id=user1.id, type="INVENTORY")
    inv2 = Inventory(name="Audit Inv 2", owner_id=user2.id, type="INVENTORY")
    inv_secret = Inventory(name="Secret Inv", owner_id=user1.id, type="INVENTORY")
    db_session.add_all([inv1, inv2, inv_secret])
    db_session.commit()

    # Direct share: inv1 shared with user2
    db_session.add(SharedInventory(user_id=user2.id, inventory_id=inv1.id))

    # Group share: inv2 shared via group with user1
    group = Group(name="Inv Audit Group", role_id=viewer_role.id)
    db_session.add(group)
    db_session.commit()
    group.users.append(user1)
    db_session.add(SharedInventoryGroup(group_id=group.id, inventory_id=inv2.id))
    db_session.commit()

    # Inventory version logs
    log_inv1 = InventoryVersion(
        inventory_id=inv1.id,
        name=inv1.name,
        type=inv1.type,
        owner_id=user1.id,
        version_num=1,
        operation="CREATE",
        changed_by_id=user1.id,
        changed_by_username=user1.username
    )
    log_inv2 = InventoryVersion(
        inventory_id=inv2.id,
        name=inv2.name,
        type=inv2.type,
        owner_id=user2.id,
        version_num=1,
        operation="CREATE",
        changed_by_id=user2.id,
        changed_by_username=user2.username
    )
    log_secret = InventoryVersion(
        inventory_id=inv_secret.id,
        name=inv_secret.name,
        type=inv_secret.type,
        owner_id=user1.id,
        version_num=1,
        operation="CREATE",
        changed_by_id=user1.id,
        changed_by_username=user1.username
    )
    db_session.add_all([log_inv1, log_inv2, log_secret])
    db_session.commit()

    token1 = create_access_token({"sub": "inv_audit_owner"})
    token2 = create_access_token({"sub": "inv_audit_shared"})
    token3 = create_access_token({"sub": "inv_audit_unauthorized"})

    # 1. User 1 (owner of inv1 & secret, group-shared on inv2) -> sees all 3
    res1 = client.get("/audit/logs/inventories", headers={"Authorization": f"Bearer {token1}"})
    assert res1.status_code == 200
    ids1 = [item["inventory_id"] for item in res1.json()]
    assert inv1.id in ids1
    assert inv2.id in ids1
    assert inv_secret.id in ids1

    # 2. User 2 (owner of inv2, direct-shared on inv1) -> sees inv1 and inv2, but NOT secret
    res2 = client.get("/audit/logs/inventories", headers={"Authorization": f"Bearer {token2}"})
    assert res2.status_code == 200
    ids2 = [item["inventory_id"] for item in res2.json()]
    assert inv1.id in ids2
    assert inv2.id in ids2
    assert inv_secret.id not in ids2

    # 3. User 2 queries specific shared inventory (inv1) -> sees log_inv1
    res2_inv1 = client.get(f"/audit/logs/inventories?inventory_id={inv1.id}", headers={"Authorization": f"Bearer {token2}"})
    assert res2_inv1.status_code == 200
    ids2_inv1 = [item["inventory_id"] for item in res2_inv1.json()]
    assert ids2_inv1 == [inv1.id]

    # 4. User 3 (unauthorized) -> sees empty list
    res3 = client.get("/audit/logs/inventories", headers={"Authorization": f"Bearer {token3}"})
    assert res3.status_code == 200
    assert len(res3.json()) == 0

    # 5. User 3 queries unauthorized inventory (inv1) -> sees empty list
    res3_inv1 = client.get(f"/audit/logs/inventories?inventory_id={inv1.id}", headers={"Authorization": f"Bearer {token3}"})
    assert res3_inv1.status_code == 200
    assert len(res3_inv1.json()) == 0

    # 6. Admin user -> sees all inventory logs
    login_admin = client.post("/auth/login", data={"username": "admin", "password": "adminpassword"})
    admin_token = login_admin.json()["access_token"]
    admin_res = client.get("/audit/logs/inventories", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_res.status_code == 200
    admin_ids = [item["inventory_id"] for item in admin_res.json()]
    assert inv1.id in admin_ids
    assert inv2.id in admin_ids
    assert inv_secret.id in admin_ids
