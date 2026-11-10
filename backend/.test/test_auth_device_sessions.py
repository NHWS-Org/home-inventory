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

from database import Base
from dependencies import get_db, init_roles_and_admin
from main import app
from models import DeviceSession, Role, RoleEnum, User
from routes.auth import hash_password

engine = create_engine(
    "sqlite:///:memory:",
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
    role = db.query(Role).filter(Role.name == RoleEnum.viewer.value).first()
    db.add(User(
        username="device_user",
        hashed_password=hash_password("password123"),
        role_id=role.id,
        is_blocked=False,
    ))
    db.commit()
    db.close()
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_login_tracks_device_details_and_expiry(setup_db):
    response = client.post(
        "/auth/login",
        data={"username": "device_user", "password": "password123"},
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "X-Client-Timezone": "Europe/Rome",
            "CF-IPCountry": "IT",
        },
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    sessions_response = client.get(
        "/auth/sessions",
        headers={"Authorization": "Bearer " + token},
    )
    assert sessions_response.status_code == 200, sessions_response.text
    session = sessions_response.json()[0]
    assert session["device_type"] == "Desktop"
    assert session["browser"] == "Chrome 120.0.0.0"
    assert session["operating_system"] == "Windows 10.0"
    assert session["region"] == "IT"
    assert session["language"] == "en-US,en;q=0.9"
    assert session["timezone"] == "Europe/Rome"
    assert session["is_current"] is True
    assert session["expires_at"]


def test_revoking_device_session_invalidates_its_token(setup_db):
    login_response = client.post(
        "/auth/login",
        data={"username": "device_user", "password": "password123"},
    )
    token = login_response.json()["access_token"]
    auth_headers = {"Authorization": "Bearer " + token}
    sessions_response = client.get("/auth/sessions", headers=auth_headers)
    assert sessions_response.status_code == 200, sessions_response.text
    sessions = sessions_response.json()
    session_id = sessions[0]["id"]

    revoke_response = client.delete(
        f"/auth/sessions/{session_id}",
        headers=auth_headers,
    )
    assert revoke_response.status_code == 200
    assert client.get("/auth/sessions", headers=auth_headers).status_code == 401

    db = TestingSessionLocal()
    session = db.query(DeviceSession).filter(DeviceSession.id == session_id).first()
    assert session.revoked_at is not None
    db.close()


def test_user_cannot_revoke_another_users_device_session(setup_db):
    db = TestingSessionLocal()
    role = db.query(Role).filter(Role.name == RoleEnum.viewer.value).first()
    db.add(User(
        username="other_user",
        hashed_password=hash_password("password123"),
        role_id=role.id,
        is_blocked=False,
    ))
    db.commit()
    db.close()

    own_login = client.post(
        "/auth/login",
        data={"username": "device_user", "password": "password123"},
    )
    other_login = client.post(
        "/auth/login",
        data={"username": "other_user", "password": "password123"},
    )
    own_token = own_login.json()["access_token"]
    other_token = other_login.json()["access_token"]
    other_headers = {"Authorization": "Bearer " + other_token}
    other_session = client.get("/auth/sessions", headers=other_headers).json()[0]

    response = client.delete(
        f"/auth/sessions/{other_session['id']}",
        headers={"Authorization": "Bearer " + own_token},
    )
    assert response.status_code == 404


def test_revoked_session_returns_unauthenticated_on_me(setup_db):
    login_response = client.post(
        "/auth/login",
        data={"username": "device_user", "password": "password123"},
    )
    token = login_response.json()["access_token"]
    auth_headers = {"Authorization": "Bearer " + token}

    me_before = client.get("/auth/me", headers=auth_headers)
    assert me_before.status_code == 200
    assert me_before.json()["username"] == "device_user"

    sessions = client.get("/auth/sessions", headers=auth_headers).json()
    session_id = sessions[0]["id"]

    revoke_resp = client.delete(f"/auth/sessions/{session_id}", headers=auth_headers)
    assert revoke_resp.status_code == 200

    me_after = client.get("/auth/me", headers=auth_headers)
    assert me_after.status_code == 200
    assert me_after.json()["id"] is None
    assert me_after.json()["username"] is None


def test_logout_invalidates_me(setup_db):
    login_response = client.post(
        "/auth/login",
        data={"username": "device_user", "password": "password123"},
    )
    token = login_response.json()["access_token"]
    auth_headers = {"Authorization": "Bearer " + token}

    me_before = client.get("/auth/me", headers=auth_headers)
    assert me_before.status_code == 200
    assert me_before.json()["username"] == "device_user"

    logout_resp = client.post("/auth/logout", headers=auth_headers)
    assert logout_resp.status_code == 200

    me_after = client.get("/auth/me", headers=auth_headers)
    assert me_after.status_code == 200
    assert me_after.json()["id"] is None
    assert me_after.json()["username"] is None
