"""P9 cache ordering, allowance math, hold mode, and commit-aware event tests."""

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from app.errors import DomainError
from app.models import Base, Card, Device, Member, OfflineAllowance, Setting, Transaction
from app.schemas.payment import PaymentRequest
from app.security.device_auth import DeviceAuthInfo
from app.security.pins import hash_pin
from app.services.allowance import (
    AllowanceService,
    assert_can_spend_online,
    compute_cached_members_for_device,
    get_total_allowances,
)
from app.services.events import CacheUpdateEvent, _bus
from app.services.ledger import InsufficientBalance, LedgerService
from app.services.payment import PaymentService
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def p9_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'allowance-p9.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, factory
    engine.dispose()


def add_device(session, device_id, *, offline=True, cap=None):
    config = {"offline_enabled": offline}
    if cap is not None:
        config["offline_card_cap"] = cap
    device = Device(
        device_id=device_id,
        name=device_id,
        type="cashier",
        token_hash=f"token-hash-{device_id}",
        status="ACTIVE",
        config_json=json.dumps(config),
    )
    session.add(device)
    session.flush()
    return device


def add_member(session, suffix, balance=50_000):
    member = Member(
        member_code=f"MG-A{suffix:05d}",
        full_name=f"Member {suffix}",
        nik_enc=f"enc-{suffix}",
        nik_idx=f"idx-{suffix}",
        balance=balance,
        status="ACTIVE",
    )
    session.add(member)
    session.flush()
    card = Card(
        member_id=member.id,
        uid=f"{suffix:08X}",
        pin_hash=hash_pin("4610"),
        status="ACTIVE",
    )
    session.add(card)
    session.flush()
    return member, card


def add_payment(session, member, device, txn_uuid, when, amount=1_000):
    session.add(
        Transaction(
            txn_uuid=txn_uuid,
            member_id=member.id,
            card_id=None,
            device_id=device.id,
            type="PAYMENT",
            amount=amount,
            direction="DEBIT",
            balance_before=member.balance + amount,
            balance_after=member.balance,
            status="COMPLETED",
            source="ONLINE",
            occurred_at=when,
            performed_by_type="DEVICE",
            performed_by_id=device.device_id,
        )
    )
    session.flush()


def device_auth(device):
    return DeviceAuthInfo(
        id=device.id,
        device_id=device.device_id,
        name=device.name,
        type=device.type,
        config_json=device.config_json,
        slot_count=device.slot_count,
        reported_mode=device.reported_mode,
    )


def test_cached_members_ordering(p9_db):
    _engine, factory = p9_db
    with factory.begin() as session:
        device_a = add_device(session, "CSH-A")
        device_b = add_device(session, "CSH-B")
        members = [add_member(session, i + 1) for i in range(5)]
        now = datetime.now(UTC)
        for i in range(3):
            add_payment(session, members[0][0], device_a, f"a1-{i}", now - timedelta(days=10 + i))
            add_payment(session, members[1][0], device_a, f"a2-{i}", now - timedelta(days=15 + i))
        for i in range(2):
            add_payment(session, members[2][0], device_a, f"a3-{i}", now - timedelta(days=2 + i))
        add_payment(session, members[3][0], device_a, "a4-1", now - timedelta(days=1))
        add_payment(session, members[4][0], device_b, "b5-1", now)
        ids = compute_cached_members_for_device(session, device_a.id, limit=4)
        assert ids == [members[0][0].id, members[1][0].id, members[2][0].id, members[3][0].id]


def test_cached_members_fill_from_other_devices(p9_db):
    _engine, factory = p9_db
    with factory.begin() as session:
        device_a = add_device(session, "CSH-A")
        device_b = add_device(session, "CSH-B")
        first, _ = add_member(session, 1)
        second, _ = add_member(session, 2)
        add_payment(session, first, device_a, "only-a", datetime.now(UTC))
        add_payment(session, second, device_b, "only-b", datetime.now(UTC) - timedelta(minutes=1))
        ids = compute_cached_members_for_device(session, device_a.id)
        assert ids == [first.id, second.id]


def test_allowance_soft_mode_default(p9_db):
    _engine, factory = p9_db
    with factory.begin() as session:
        a = add_device(session, "CSH-A")
        b = add_device(session, "CSH-B")
        member, _ = add_member(session, 1, 100_000)
        add_payment(session, member, a, "soft-seed", datetime.now(UTC))
        AllowanceService(session).apply_allowances(member.id)
    with factory() as session:
        rows = session.scalars(
            select(OfflineAllowance).where(OfflineAllowance.member_id == member.id)
        ).all()
        assert {row.device_id: row.amount for row in rows} == {a.id: 50_000, b.id: 50_000}
    with factory.begin() as session:
        session.get(Member, member.id).balance = 30_000
        AllowanceService(session).apply_allowances(member.id)
    with factory() as session:
        rows = session.scalars(select(OfflineAllowance).where(OfflineAllowance.member_id == member.id)).all()
        assert {row.device_id: row.amount for row in rows} == {a.id: 15_000, b.id: 15_000}


def test_allowance_hard_mode_blocks_overspend(p9_db):
    _engine, factory = p9_db
    with factory.begin() as session:
        a = add_device(session, "CSH-A")
        add_device(session, "CSH-B")
        member, card = add_member(session, 1, 50_000)
        add_payment(session, member, a, "hard-seed", datetime.now(UTC))
        session.add(Setting(key="offline_hold_mode", value='"hard"'))
        AllowanceService(session).apply_allowances(member.id)
    payload = PaymentRequest(
        txn_uuid="hard-pay",
        uid=card.uid,
        amount=30_000,
        ts=int(time.time()),
        pin="4610",
    )
    with factory() as session:
        with pytest.raises(InsufficientBalance):
            assert_can_spend_online(session, member.id, payload.amount)
        with pytest.raises(DomainError) as exc:
            PaymentService(session).process_payment(session, device_auth(a), payload)
        assert exc.value.code == "INSUFFICIENT_BALANCE"


def test_allowance_hard_mode_partial_spend(p9_db):
    _engine, factory = p9_db
    with factory.begin() as session:
        device = add_device(session, "CSH-A", cap=25_000)
        member, card = add_member(session, 1, 50_000)
        add_payment(session, member, device, "partial-seed", datetime.now(UTC))
        session.add(Setting(key="offline_hold_mode", value='"hard"'))
        AllowanceService(session).apply_allowances(member.id)
    payload = PaymentRequest(
        txn_uuid="partial-pay",
        uid=card.uid,
        amount=20_000,
        ts=int(time.time()),
        pin="4610",
    )
    with factory() as session:
        result = PaymentService(session).process_payment(session, device_auth(device), payload)
        assert result.balance_after == 30_000
    with factory() as session:
        assert get_total_allowances(session, member.id) == 25_000
        assert session.get(Member, member.id).balance == 30_000


def test_allowance_sum_never_exceeds_balance(p9_db):
    _engine, factory = p9_db
    with factory.begin() as session:
        devices = [add_device(session, f"CSH-{i}") for i in range(3)]
        for i, balance in enumerate([1_000, 15_000, 30_000, 100_000]):
            member, _ = add_member(session, i + 1, balance)
            add_payment(session, member, devices[i % 3], f"sum-{i}", datetime.now(UTC))
            AllowanceService(session).apply_allowances(member.id)
    with factory() as session:
        for member in session.scalars(select(Member)).all():
            assert get_total_allowances(session, member.id) <= member.balance


def test_cache_update_event_published_after_commit(p9_db):
    _engine, factory = p9_db
    received = []
    unsubscribe = _bus.subscribe(CacheUpdateEvent, received.append)
    try:
        with factory.begin() as session:
            device = add_device(session, "CSH-A")
            member, card = add_member(session, 1, 50_000)
            add_payment(session, member, device, "event-seed", datetime.now(UTC))
        with factory() as session:
            payload = PaymentRequest(
                txn_uuid="event-payment",
                uid=card.uid,
                amount=1_000,
                ts=int(time.time()),
                pin="4610",
            )
            PaymentService(session).process_payment(session, device_auth(device), payload)
        assert len(received) == 1
        assert received[0].member_id == member.id
        assert received[0].uid_list == [card.uid]
    finally:
        unsubscribe()


def test_cache_update_event_not_published_on_rollback(p9_db):
    _engine, factory = p9_db
    received = []
    unsubscribe = _bus.subscribe(CacheUpdateEvent, received.append)
    try:
        with factory.begin() as session:
            device = add_device(session, "CSH-A")
            member, _ = add_member(session, 1, 50_000)
            add_payment(session, member, device, "rollback-seed", datetime.now(UTC))
        with factory() as session, pytest.raises(RuntimeError), session.begin():
            LedgerService(session)._credit_internal(
                member.id,
                1_000,
                txn_uuid="rolled-back-credit",
                type="TOPUP",
                source="ADMIN",
                performed_by_type="ADMIN",
                performed_by_id="1",
            )
            raise RuntimeError("force rollback after balance mutation")
        assert received == []
    finally:
        unsubscribe()


def test_payment_service_uses_hold_mode_check(p9_db):
    _engine, factory = p9_db
    with factory.begin() as session:
        a = add_device(session, "CSH-A")
        add_device(session, "CSH-B")
        member, card = add_member(session, 1, 50_000)
        add_payment(session, member, a, "payment-hold-seed", datetime.now(UTC))
        session.add(Setting(key="offline_hold_mode", value='"hard"'))
        AllowanceService(session).apply_allowances(member.id)
    payload = PaymentRequest(
        txn_uuid="payment-hold-check",
        uid=card.uid,
        amount=1_000,
        ts=int(time.time()),
        pin="4610",
    )
    with factory() as session:
        with pytest.raises(DomainError) as exc:
            PaymentService(session).process_payment(session, device_auth(a), payload)
        assert exc.value.code == "INSUFFICIENT_BALANCE"
