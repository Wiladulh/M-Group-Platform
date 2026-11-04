"""SQLAlchemy database engine and session configuration."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import get_settings


settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")

_connect_args = {"check_same_thread": False, "timeout": 5} if _is_sqlite else {}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
)


if _is_sqlite:

    @event.listens_for(Engine, "connect")
    def configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
        """Apply required SQLite safety and concurrency pragmas per connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class for future SQLAlchemy models; no tables are declared in P1."""
