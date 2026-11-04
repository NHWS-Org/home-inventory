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
from models import User, Role, RoleEnum
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

def test_read_setting_unauthenticated_fails(db_session):
    response = client.get("/settings/settings/ENABLE_REGISTRATION")
    assert response.status_code in (401, 403)

def test_read_setting_non_admin_fails(db_session):
    viewer_role = db_session.query(Role).filter(Role.name == RoleEnum.viewer.value).first()
    viewer_user = User(
        username="viewer_user",
        hashed_password=hash_password("password123"),
        role_id=viewer_role.id,
        is_blocked=False
    )
    db_session.add(viewer_user)
    db_session.commit()

    token = create_access_token({"sub": "viewer_user"})
    response = client.get(
        "/settings/settings/ENABLE_REGISTRATION",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403

def test_read_setting_admin_succeeds(db_session):
    login_res = client.post(
        "/auth/login",
        data={"username": "admin", "password": "adminpassword"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    response = client.get(
        "/settings/settings/ENABLE_REGISTRATION",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["key"] == "ENABLE_REGISTRATION"

def test_read_nonexistent_setting_returns_404(db_session):
    login_res = client.post(
        "/auth/login",
        data={"username": "admin", "password": "adminpassword"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    response = client.get(
        "/settings/settings/NON_EXISTENT_SETTING_KEY",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Impostazione non trovata"

def test_delete_nonexistent_setting_returns_404(db_session):
    login_res = client.post(
        "/auth/login",
        data={"username": "admin", "password": "adminpassword"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    response = client.delete(
        "/settings/settings/NON_EXISTENT_SETTING_KEY",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Impostazione non trovata"
