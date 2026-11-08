"""Background worker regression tests for automatic refunds and session expiry."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app import db
from app.main import app, lifespan
from app.models import (
    AdminSession,
    AdminUser,
    Base,
    Card,
    Device,
    Member,
    OfflineAllowance,
    Transaction,
)
from app.services.admin_session_monitor import admin_session_monitor_once
from app.services.background_tasks import pending_dispense_monitor_once
from app.services.events import CacheUpdateEvent, _bus
from app.services.ledger import LedgerService
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def background_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'background.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        admin = AdminUser(
            id=1,
            username="admin",
            display_name="Administrator",
            password_hash="test-hash",
            must_change_password=False,
        )
        member = Member(
            member_code="MG-A00001",
            full_name="Background Member",
            nik_enc="enc",
            nik_idx="background-idx",
            balance=10_000,
            status="ACTIVE",
        )
        device = Device(
            device_id="VND-BG-001",
            name="Background vending",
            type="vending",
            token_hash="d" * 64,
            status="ACTIVE",
            slot_count=5,
            config_json='{"offline_enabled":true}',
        )
        session.add_all([admin, member, device])
        session.flush()
        card = Card(
            member_id=member.id,
            uid="A1B2C3D4",
            pin_hash="test-pin-hash",
            status="ACTIVE",
            bound_at=datetime.now(UTC),
        )
        session.add(card)
        session.flush()
        member_id, device_id, card_id, admin_id = member.id, device.id, card.id, admin.id
        session.add(
            OfflineAllowance(
                member_id=member_id,
                device_id=device_id,
                amount=10_000,
                computed_at=datetime.now(UTC),
                version=1,
            )
        )
    with factory() as session:
        original = LedgerService(session).debit(
            member_id,
            2_000,
            txn_uuid="pending-dispense-test",
            card_id=card_id,
            device_id=device_id,
            type="PAYMENT",
            source="ONLINE",
            performed_by_type="DEVICE",
            performed_by_id="VND-BG-001",
        )
        txn_id = original.id
    monkeypatch.setattr(db, "SessionLocal", factory)
    yield engine, factory, member_id, device_id, card_id, admin_id, txn_id
    engine.dispose()


def _set_transaction_created_at(factory, txn_id, value):
    with factory.begin() as session:
        row = session.get(Transaction, txn_id)
        row.status = "PENDING_DISPENSE"
        row.created_at = value


def _add_admin_session(factory, admin_id, session_hash, expires_at):
    with factory.begin() as session:
        row = AdminSession(
            user_id=admin_id,
            session_hash=session_hash,
            last_seen_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        session.add(row)
        session.flush()
        return row.id


def test_pending_dispense_refund_after_2min(background_db):
    _engine, factory, member_id, _device_id, _card_id, _admin_id, txn_id = background_db
    _set_transaction_created_at(factory, txn_id, datetime.now(UTC) - timedelta(minutes=3))
    published = []
    unsubscribe = _bus.subscribe(CacheUpdateEvent, published.append)
    try:
        assert asyncio.run(pending_dispense_monitor_once()) == 1
    finally:
        unsubscribe()
    with factory() as session:
        original = session.get(Transaction, txn_id)
        refunds = session.scalars(
            select(Transaction).where(
                Transaction.ref_txn_id == txn_id,
                Transaction.type == "REFUND",
                Transaction.direction == "CREDIT",
            )
        ).all()
        assert original.status == "DISPENSE_FAILED"
        assert len(refunds) == 1
        assert session.get(Member, member_id).balance == 10_000
        assert any(event.member_id == member_id for event in published)


def test_pending_dispense_not_refunded_before_2min(background_db):
    _engine, factory, member_id, _device_id, _card_id, _admin_id, txn_id = background_db
    _set_transaction_created_at(factory, txn_id, datetime.now(UTC) - timedelta(seconds=30))
    assert asyncio.run(pending_dispense_monitor_once()) == 0
    with factory() as session:
        assert session.get(Transaction, txn_id).status == "PENDING_DISPENSE"
        assert session.get(Member, member_id).balance == 8_000
        assert (
            session.scalar(select(Transaction.id).where(Transaction.ref_txn_id == txn_id)) is None
        )


def test_pending_dispense_idempotent(background_db):
    _engine, factory, member_id, _device_id, _card_id, _admin_id, txn_id = background_db
    _set_transaction_created_at(factory, txn_id, datetime.now(UTC) - timedelta(minutes=3))
    assert asyncio.run(pending_dispense_monitor_once()) == 1
    assert asyncio.run(pending_dispense_monitor_once()) == 0
    with factory() as session:
        assert session.get(Transaction, txn_id).status == "DISPENSE_FAILED"
        assert session.get(Member, member_id).balance == 10_000
        assert (
            len(
                session.scalars(
                    select(Transaction).where(
                        Transaction.ref_txn_id == txn_id,
                        Transaction.type == "REFUND",
                    )
                ).all()
            )
            == 1
        )


def test_admin_session_monitor_revokes_expired(background_db):
    _engine, factory, _member_id, _device_id, _card_id, admin_id, _txn_id = background_db
    expired_id = _add_admin_session(
        factory, admin_id, "a" * 64, datetime.now(UTC) - timedelta(minutes=1)
    )
    assert asyncio.run(admin_session_monitor_once()) == 1
    with factory() as session:
        assert session.get(AdminSession, expired_id).revoked_at is not None


def test_admin_session_monitor_skips_active(background_db):
    _engine, factory, _member_id, _device_id, _card_id, admin_id, _txn_id = background_db
    active_id = _add_admin_session(
        factory, admin_id, "b" * 64, datetime.now(UTC) + timedelta(hours=1)
    )
    assert asyncio.run(admin_session_monitor_once()) == 0
    with factory() as session:
        assert session.get(AdminSession, active_id).revoked_at is None


def test_admin_session_monitor_idempotent(background_db):
    _engine, factory, _member_id, _device_id, _card_id, admin_id, _txn_id = background_db
    expired_id = _add_admin_session(
        factory, admin_id, "c" * 64, datetime.now(UTC) - timedelta(minutes=1)
    )
    assert asyncio.run(admin_session_monitor_once()) == 1
    assert asyncio.run(admin_session_monitor_once()) == 0
    with factory() as session:
        assert session.get(AdminSession, expired_id).revoked_at is not None


def test_all_four_loops_registered_in_lifespan(monkeypatch):
    import app.main as main

    async def no_op():
        return None

    monkeypatch.setattr(main.engine, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(main.engine, "dispose", lambda: None)
    monkeypatch.setattr(main.broadcast_bus, "start", no_op)
    monkeypatch.setattr(main.broadcast_bus, "stop", no_op)

    async def exercise_lifespan():
        async with lifespan(app):
            names = {
                task.get_coro().cr_code.co_name
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task()
            }
            assert names >= {
                "bind_expiry_loop",
                "offline_monitor_loop",
                "pending_dispense_monitor_loop",
                "admin_session_monitor_loop",
            }

    asyncio.run(exercise_lifespan())
