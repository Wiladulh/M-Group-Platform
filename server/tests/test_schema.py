"""Database migration and SQLite constraint tests."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

SERVER_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = SERVER_DIR / "alembic.ini"
EXPECTED_TABLES = {
    "admin_users",
    "admin_sessions",
    "members",
    "cards",
    "devices",
    "device_events",
    "products",
    "vending_slots",
    "catalog_meta",
    "transactions",
    "offline_allowances",
    "shortfall_records",
    "pending_sync_log",
    "card_bind_sessions",
    "operators",
    "operator_devices",
    "topup_requests",
    "audit_logs",
    "settings",
}


def make_engine():
    """Create an isolated in-memory SQLite engine with safety pragmas."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def migrate(engine, revision: str) -> None:
    """Run an Alembic revision against the supplied test connection."""
    config = Config(str(ALEMBIC_INI))
    connection = engine.connect()
    config.attributes["connection"] = connection
    try:
        if revision == "head":
            command.upgrade(config, revision)
        else:
            command.downgrade(config, revision)
    finally:
        connection.close()


@pytest.fixture
def schema_engine():
    engine = make_engine()
    migrate(engine, "head")
    yield engine
    engine.dispose()


def insert_member(connection) -> int:
    result = connection.execute(
        text(
            """
            INSERT INTO members (member_code, full_name, nik_enc, nik_idx, balance, status)
            VALUES ('MG-A00001', 'Anggota Uji', 'encrypted-value', 'blind-index', 10000, 'ACTIVE')
            """
        )
    )
    return result.lastrowid


def test_alembic_upgrade_head_creates_complete_schema() -> None:
    engine = make_engine()
    try:
        migrate(engine, "head")
        tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert tables == EXPECTED_TABLES
        assert len(tables) == 19
    finally:
        engine.dispose()


def test_alembic_downgrade_base_removes_schema() -> None:
    engine = make_engine()
    try:
        migrate(engine, "head")
        migrate(engine, "base")
        tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert tables == set()
    finally:
        engine.dispose()


def test_member_code_format_is_enforced(schema_engine) -> None:
    with schema_engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO members (member_code, full_name, nik_enc, nik_idx, balance, status)
                    VALUES ('INVALID-1', 'Anggota Uji', 'enc', 'idx', 0, 'ACTIVE')
                    """
                )
            )
        transaction.rollback()


def test_card_uid_requires_supported_uppercase_hex(schema_engine) -> None:
    with schema_engine.connect() as connection:
        transaction = connection.begin()
        member_id = insert_member(connection)
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO cards (member_id, uid, pin_hash, status)
                    VALUES (:member_id, '04g1', 'argon-hash', 'ACTIVE')
                    """
                ),
                {"member_id": member_id},
            )
        transaction.rollback()


def test_members_reject_negative_balance(schema_engine) -> None:
    with schema_engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO members (member_code, full_name, nik_enc, nik_idx, balance, status)
                    VALUES ('MG-A00001', 'Anggota Uji', 'enc', 'idx', -1, 'ACTIVE')
                    """
                )
            )
        transaction.rollback()


def test_only_one_active_or_locked_card_per_member(schema_engine) -> None:
    with schema_engine.connect() as connection:
        transaction = connection.begin()
        member_id = insert_member(connection)
        connection.execute(
            text(
                """
                INSERT INTO cards (member_id, uid, pin_hash, status)
                VALUES (:member_id, '04A1B2C3', 'argon-hash', 'ACTIVE')
                """
            ),
            {"member_id": member_id},
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO cards (member_id, uid, pin_hash, status)
                    VALUES (:member_id, '04D4E5F6', 'argon-hash', 'ACTIVE')
                    """
                ),
                {"member_id": member_id},
            )
        transaction.rollback()


def test_transactions_reject_nonpositive_amount(schema_engine) -> None:
    with schema_engine.connect() as connection:
        transaction = connection.begin()
        member_id = insert_member(connection)
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO transactions (
                        txn_uuid, member_id, type, amount, direction,
                        balance_before, balance_after, status, source,
                        occurred_at, performed_by_type
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000001', :member_id,
                        'PAYMENT', 0, 'DEBIT', 10000, 10000, 'COMPLETED',
                        'ONLINE', CURRENT_TIMESTAMP, 'DEVICE'
                    )
                    """
                ),
                {"member_id": member_id},
            )
        transaction.rollback()
