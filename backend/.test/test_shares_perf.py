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
from models import User, Role, RoleEnum, Inventory, SharedInventory
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

def test_list_shares_query_count_is_constant(setup_db):
    """Verify that listing inventory shares does not execute N+1 queries as number of shared users grows."""
    db = TestingSessionLocal()
    admin_role = db.query(Role).filter(Role.name == RoleEnum.admin.value).first()
    mod_role = db.query(Role).filter(Role.name == RoleEnum.moderator.value).first()

    owner = User(username="owner_user", hashed_password=hash_password("pw"), role_id=admin_role.id)
    db.add(owner)
    db.commit()

    inv = Inventory(name="Shared Inventory", owner_id=owner.id, type="INVENTORY")
    db.add(inv)
    db.commit()
    inv_id = inv.id

    # Create 10 shared users
    users = []
    for i in range(10):
        u = User(username=f"shared_user_{i}", hashed_password=hash_password("pw"), role_id=mod_role.id)
        db.add(u)
        users.append(u)
    db.commit()

    for u in users:
        db.add(SharedInventory(inventory_id=inv_id, user_id=u.id))
    db.commit()
    db.close()

    token = create_access_token({"sub": "owner_user"})

    queries = []
    def track_queries(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", track_queries)

    try:
        res = client.get(
            f"/inventory/share/{inv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 10
        returned_usernames = {u["username"] for u in data}
        assert returned_usernames == {f"shared_user_{i}" for i in range(10)}

        # If N+1 were present, query count would exceed 15 (e.g. 23 queries).
        # With optimization, query count should be <= 5 (auth + inventory lookup + 1 joined user query).
        assert len(queries) <= 5, f"Too many queries executed: {len(queries)}"
    finally:
        event.remove(engine, "before_cursor_execute", track_queries)
