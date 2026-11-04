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
from models import User, Role, RoleEnum, Inventory, SharedInventory, FilterTemplate, MetadataDefinition, MetadataDefinitionAssignment
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

def test_private_filter_template_authorization(db_session):
    # Setup roles and users
    viewer_role = db_session.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    user1 = User(
        username="filter_owner",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    user2 = User(
        username="filter_attacker",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    db_session.add(user1)
    db_session.add(user2)
    db_session.commit()

    # Create inventory owned by user1 and shared with user2
    inv = Inventory(name="Shared Inventory", owner_id=user1.id, type="INVENTORY")
    db_session.add(inv)
    db_session.commit()

    shared_inv = SharedInventory(user_id=user2.id, inventory_id=inv.id)
    db_session.add(shared_inv)
    db_session.commit()

    # User 1 creates private unbound template
    token1 = create_access_token({"sub": "filter_owner"})
    create_res = client.post(
        "/filter-templates",
        headers={"Authorization": f"Bearer {token1}"},
        json={
            "name": "User 1 Private Filter",
            "description": "Secret filter criteria",
            "filter_type": "text",
            "criteria": {"criteria": []},
            "is_shared": False
        }
    )
    assert create_res.status_code == 201
    template_id = create_res.json()["id"]

    # User 1 creates shared unbound template
    create_shared_res = client.post(
        "/filter-templates",
        headers={"Authorization": f"Bearer {token1}"},
        json={
            "name": "User 1 Shared Filter",
            "description": "Public filter criteria",
            "filter_type": "text",
            "criteria": {"criteria": []},
            "is_shared": True
        }
    )
    assert create_shared_res.status_code == 201
    shared_template_id = create_shared_res.json()["id"]

    token2 = create_access_token({"sub": "filter_attacker"})

    # 1. Attacker attempts to fetch User 1's private template directly -> Expect 403
    get_res = client.get(
        f"/filter-templates/{template_id}",
        headers={"Authorization": f"Bearer {token2}"}
    )
    assert get_res.status_code == 403

    # 2. Attacker attempts to fetch User 1's shared template directly -> Expect 200
    get_shared_res = client.get(
        f"/filter-templates/{shared_template_id}",
        headers={"Authorization": f"Bearer {token2}"}
    )
    assert get_shared_res.status_code == 200

    # 3. Attacker lists templates for the inventory -> Private template should not be listed
    list_res = client.get(
        f"/filter-templates?inventory_id={inv.id}",
        headers={"Authorization": f"Bearer {token2}"}
    )
    assert list_res.status_code == 200
    listed_ids = [t["id"] for t in list_res.json()]
    assert template_id not in listed_ids
    assert shared_template_id in listed_ids

    # 4. Owner lists templates -> Private template SHOULD be listed
    owner_list_res = client.get(
        f"/filter-templates?inventory_id={inv.id}",
        headers={"Authorization": f"Bearer {token1}"}
    )
    assert owner_list_res.status_code == 200
    owner_listed_ids = [t["id"] for t in owner_list_res.json()]
    assert template_id in owner_listed_ids

    # 5. Admin fetches private template -> Expect 200
    login_admin = client.post(
        "/auth/login",
        data={"username": "admin", "password": "adminpassword"}
    )
    admin_token = login_admin.json()["access_token"]
    admin_get_res = client.get(
        f"/filter-templates/{template_id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert admin_get_res.status_code == 200


def test_inventory_bound_filter_template_authorization(db_session):
    viewer_role = db_session.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    user1 = User(
        username="inv_owner",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    user_unauthorized = User(
        username="unauthorized_user",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    user_authorized = User(
        username="authorized_user",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    db_session.add_all([user1, user_unauthorized, user_authorized])
    db_session.commit()

    # Private inventory for user1, shared with user_authorized
    secret_inv = Inventory(name="Secret Inventory", owner_id=user1.id, type="INVENTORY")
    db_session.add(secret_inv)
    db_session.commit()

    db_session.add(SharedInventory(user_id=user_authorized.id, inventory_id=secret_inv.id))
    db_session.commit()

    # Create a shared template bound to secret_inv directly in DB
    shared_bound_template = FilterTemplate(
        inventory_id=secret_inv.id,
        name="Shared Bound Template",
        filter_type="text",
        criteria={},
        is_shared=True,
        user_ins=user1.id,
        user_mod=user1.id
    )
    # Create a private template bound to secret_inv directly in DB
    private_bound_template = FilterTemplate(
        inventory_id=secret_inv.id,
        name="Private Bound Template",
        filter_type="text",
        criteria={},
        is_shared=False,
        user_ins=user1.id,
        user_mod=user1.id
    )
    db_session.add_all([shared_bound_template, private_bound_template])
    db_session.commit()

    unauth_token = create_access_token({"sub": "unauthorized_user"})
    auth_token = create_access_token({"sub": "authorized_user"})

    # 1. Unauthorized user attempts to fetch shared bound template -> 403 (no inventory access)
    res1 = client.get(
        f"/filter-templates/{shared_bound_template.id}",
        headers={"Authorization": f"Bearer {unauth_token}"}
    )
    assert res1.status_code == 403

    # 2. Authorized user fetches shared bound template -> 200 (has inventory access and is_shared=True)
    res2 = client.get(
        f"/filter-templates/{shared_bound_template.id}",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert res2.status_code == 200

    # 3. Authorized non-owner user attempts to fetch private bound template -> 403 (not template owner)
    res3 = client.get(
        f"/filter-templates/{private_bound_template.id}",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert res3.status_code == 403


def test_scope_preview_does_not_leak_private_inventories(db_session):
    viewer_role = db_session.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    user1 = User(
        username="scope_owner",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    user2 = User(
        username="scope_attacker",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    db_session.add_all([user1, user2])
    db_session.commit()

    # Private inventory for user1 only
    secret_inv = Inventory(name="Top Secret Vault", owner_id=user1.id, type="INVENTORY")
    # Shared inventory for user1, shared with user2
    public_inv = Inventory(name="Public Shared Inventory", owner_id=user1.id, type="INVENTORY")
    db_session.add_all([secret_inv, public_inv])
    db_session.commit()

    db_session.add(SharedInventory(user_id=user2.id, inventory_id=public_inv.id))
    db_session.commit()

    # Create metadata definition and assign globally
    meta_def = MetadataDefinition(
        key="color_attr",
        label="Color Attribute",
        field_type="TEXT",
        is_active=True,
        user_ins=user1.id,
        user_mod=user1.id
    )
    db_session.add(meta_def)
    db_session.commit()

    assignment = MetadataDefinitionAssignment(
        definition_id=meta_def.id,
        scope="GLOBAL",
        user_ins=user1.id,
        user_mod=user1.id
    )
    db_session.add(assignment)
    db_session.commit()

    # Create a shared filter template
    shared_template = FilterTemplate(
        name="Global Color Template",
        filter_type="text",
        criteria={"criteria": [{"definition_id": meta_def.id}]},
        is_shared=True,
        user_ins=user1.id,
        user_mod=user1.id
    )
    db_session.add(shared_template)
    db_session.commit()

    attacker_token = create_access_token({"sub": "scope_attacker"})

    # 1. Attacker queries scope-preview endpoint
    preview_res = client.get(
        f"/filter-templates/scope-preview?definition_ids={meta_def.id}",
        headers={"Authorization": f"Bearer {attacker_token}"}
    )
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    visible_inventory_ids = [inv["id"] for inv in preview_data.get("inventories", [])]
    assert secret_inv.id not in visible_inventory_ids

    # 2. Attacker lists filter templates for public_inv
    list_res = client.get(
        f"/filter-templates?inventory_id={public_inv.id}",
        headers={"Authorization": f"Bearer {attacker_token}"}
    )
    assert list_res.status_code == 200
    templates_data = list_res.json()
    assert len(templates_data) > 0
    scope_preview_inventories = templates_data[0].get("scope_preview", {}).get("inventories", [])
    scope_inventory_ids = [inv["id"] for inv in scope_preview_inventories]
    assert secret_inv.id not in scope_inventory_ids
