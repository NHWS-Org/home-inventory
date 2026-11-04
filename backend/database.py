import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from models import Base

load_dotenv()

DEFAULT_SQLITE_URL = "sqlite:///./data/inventory.db"
_DATABASE_URL = os.getenv("DATABASE_URL")
_DATABASE_TYPE = os.getenv("DATABASE_TYPE")


def _normalize_database_type(database_type: str) -> str:
    normalized = database_type.strip().upper()
    aliases = {
        "MYSQL": "MYSQL",
        "MARIADB": "MYSQL",
        "MYSQL/MARIADB": "MYSQL",
        "POSTGRES": "POSTGRES",
        "POSTGRESQL": "POSTGRES",
        "SQLITE": "SQLITE",
    }
    if normalized not in aliases:
        raise ValueError(
            "DATABASE_TYPE deve essere SQLITE, MYSQL, MARIADB o POSTGRES"
        )
    return aliases[normalized]


if _DATABASE_TYPE:
    DATABASE_TYPE = _normalize_database_type(_DATABASE_TYPE)
elif _DATABASE_URL:
    _url_dialect = make_url(_DATABASE_URL).get_backend_name()
    DATABASE_TYPE = {
        "sqlite": "SQLITE",
        "mysql": "MYSQL",
        "mariadb": "MYSQL",
        "postgresql": "POSTGRES",
    }.get(_url_dialect, "")
    if not DATABASE_TYPE:
        raise ValueError(f"Dialect database non supportato: {_url_dialect}")
else:
    DATABASE_TYPE = "SQLITE"

if DATABASE_TYPE != "SQLITE" and not _DATABASE_URL:
    raise ValueError(f"DATABASE_URL è obbligatorio per DATABASE_TYPE={DATABASE_TYPE}")

DATABASE_URL = _DATABASE_URL or DEFAULT_SQLITE_URL
url = make_url(DATABASE_URL)
url_database_type = {
    "sqlite": "SQLITE",
    "mysql": "MYSQL",
    "mariadb": "MYSQL",
    "postgresql": "POSTGRES",
}.get(url.get_backend_name())
if url_database_type != DATABASE_TYPE:
    raise ValueError(
        f"DATABASE_TYPE={DATABASE_TYPE} non corrisponde al dialect "
        f"di DATABASE_URL ({url.get_backend_name()})"
    )

if DATABASE_TYPE == "SQLITE" and url.database not in (None, "", ":memory:"):
    Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

engine_options = (
    {"connect_args": {"check_same_thread": False}}
    if DATABASE_TYPE == "SQLITE"
    else {}
)
engine = create_engine(DATABASE_URL, **engine_options)
if DATABASE_TYPE == "SQLITE":
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    print("ℹ️ Creazione delle tabelle...")
    print("ℹ️ Modelli registrati:", Base.metadata.tables.keys())
    Base.metadata.create_all(bind=engine)
    print("✅ Tabelle create con successo!")
