import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from dependencies import get_current_user, get_db
from models import Role, Setting, User
from routes.settings import router as settings_router
from routes.system import router as system_router


@pytest.fixture
def api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([Role(id=1, name="admin"), Role(id=2, name="moderator"), Role(id=3, name="viewer")])
        db.add(Setting(key="UI_RECENT_ITEMS_LIMIT", value="7"))
    app = FastAPI()
    app.include_router(system_router, prefix="/system")
    app.include_router(settings_router, prefix="/settings")

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client, app, factory
    engine.dispose()


@pytest.mark.parametrize("role", ["admin", "moderator", "viewer"])
def test_authenticated_roles_can_read_only_the_recent_limit(api, role):
    client, app, factory = api
    with factory() as db:
        role_obj = db.query(Role).filter_by(name=role).one()
        user = User(id=1, username="test", role=role_obj)
    app.dependency_overrides[get_current_user] = lambda: user
    assert client.get("/system/recent-items-limit").json() == {"limit": 7}
    if role != "admin":
        assert client.get("/settings/settings/UI_RECENT_ITEMS_LIMIT").status_code == 403
        assert client.get("/settings/settings/ENABLE_REGISTRATION").status_code == 403
        assert client.post("/settings/settings", json={"key": "UI_RECENT_ITEMS_LIMIT", "value": "9"}).status_code == 403


def test_limit_requires_authentication(api):
    client, _, _ = api
    assert client.get("/system/recent-items-limit").status_code == 401


@pytest.mark.parametrize("value", ["not-a-number", "0", "-1", None])
def test_invalid_or_missing_setting_is_reported(api, value):
    client, app, factory = api
    app.dependency_overrides[get_current_user] = lambda: User(id=1, username="test")
    with factory.begin() as db:
        setting = db.get(Setting, "UI_RECENT_ITEMS_LIMIT")
        if value is None:
            db.delete(setting)
        else:
            setting.value = value
    response = client.get("/system/recent-items-limit")
    assert response.status_code == 500
    assert response.json()["detail"] == "Impostazione UI_RECENT_ITEMS_LIMIT mancante o non valida"
