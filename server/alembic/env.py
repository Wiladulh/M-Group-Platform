"""Alembic environment configured from application settings and metadata."""

from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.db import engine
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
settings = get_settings()


def run_migrations_offline() -> None:
    """Run migrations without creating an Engine."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection) -> None:
    """Run migrations on a caller-provided SQLAlchemy connection."""
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a test-provided connection or the application Engine."""
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with_connection(connection)
    else:
        with engine.connect() as connection:
            _run_with_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
