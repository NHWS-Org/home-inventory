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
from dependencies import get_db, init_roles_and_admin
from models import User, Role, RoleEnum, Inventory
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
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    init_roles_and_admin(db)
    db.close()
    yield
    app.dependency_overrides.clear()

client = TestClient(app)

def test_moderator_can_get_shareable_users_for_own_inventory(setup_db):
    db = TestingSessionLocal()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()
    viewer_role = db.query(Role).filter(Role.name == RoleEnum.viewer.value).first()

    mod_user = User(
        username="mod1",
        hashed_password=hash_password("modpassword"),
        role_id=mod_role.id
    )
    viewer_user = User(
        username="viewer1",
        hashed_password=hash_password("viewerpassword"),
        role_id=viewer_role.id
    )
    db.add(mod_user)
    db.add(viewer_user)
    db.commit()

    inv = Inventory(name="Mod's Inventory", owner_id=mod_user.id, type="INVENTORY")
    db.add(inv)
    db.commit()
    inv_id = inv.id
    db.close()

    token = create_access_token({"sub": "mod1"})
    res = client.get(
        f"/user/users/shareable/{inv_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    usernames = [u["username"] for u in res.json()]
    assert "mod1" in usernames
    assert "viewer1" in usernames
    assert "admin" not in usernames

def test_moderator_cannot_get_shareable_users_for_unauthorized_inventory(setup_db):
    db = TestingSessionLocal()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()
    mod1 = User(username="mod_owner", hashed_password=hash_password("password"), role_id=mod_role.id)
    mod2 = User(username="mod_attacker", hashed_password=hash_password("password"), role_id=mod_role.id)
    db.add(mod1)
    db.add(mod2)
    db.commit()

    inv = Inventory(name="Private Inventory", owner_id=mod1.id, type="INVENTORY")
    db.add(inv)
    db.commit()
    inv_id = inv.id
    db.close()

    token = create_access_token({"sub": "mod_attacker"})
    res = client.get(
        f"/user/users/shareable/{inv_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403

def test_viewer_cannot_get_shareable_users(setup_db):
    db = TestingSessionLocal()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()
    viewer_role = db.query(Role).filter(Role.name == RoleEnum.viewer.value).first()
    mod1 = User(username="mod_owner2", hashed_password=hash_password("password"), role_id=mod_role.id)
    viewer1 = User(username="viewer_user", hashed_password=hash_password("password"), role_id=viewer_role.id)
    db.add(mod1)
    db.add(viewer1)
    db.commit()

    inv = Inventory(name="Mod Inventory 2", owner_id=mod1.id, type="INVENTORY")
    db.add(inv)
    db.commit()
    inv_id = inv.id
    db.close()

    token = create_access_token({"sub": "viewer_user"})
    res = client.get(
        f"/user/users/shareable/{inv_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403

def test_admin_user_management_still_requires_admin(setup_db):
    db = TestingSessionLocal()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()
    mod_user = User(username="mod_admin_test", hashed_password=hash_password("password"), role_id=mod_role.id)
    db.add(mod_user)
    db.commit()
    db.close()

    token = create_access_token({"sub": "mod_admin_test"})
    res = client.get(
        "/user/users/",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403
