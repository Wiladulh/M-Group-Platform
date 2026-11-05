"""Ledger invariants, idempotency, and SQLite concurrency tests."""

import random
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO

import pytest

from app.models import Base, Member, Transaction
from app.services.ledger import (
    IdempotencyConflict,
    InsufficientBalance,
    LedgerService,
)
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ledger-test.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    # Acquire the SQLite write reservation at transaction start. This avoids
    # deferred read-to-write lock upgrades while retaining atomic UPDATE logic.
    @event.listens_for(engine, "begin")
    def begin_immediate(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, factory
    engine.dispose()


def add_member(factory, balance=10_000, suffix=1):
    with factory.begin() as session:
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
        return member.id


def debit(service, member_id, amount=5_000, txn_uuid="debit-1"):
    return service.debit(
        member_id,
        amount,
        txn_uuid=txn_uuid,
        card_id=None,
        device_id=None,
        type="PAYMENT",
        source="ONLINE",
        performed_by_type="DEVICE",
        performed_by_id="CSH-001",
    )


def ledger_sums(session, member_id):
    rows = session.scalars(
        select(Transaction).where(Transaction.member_id == member_id)
    ).all()
    credits = sum(
        row.amount for row in rows
        if row.direction == "CREDIT" and row.status in {
            "COMPLETED", "PENDING_DISPENSE", "DISPENSE_FAILED", "REVERSED"
        }
    )
    debits = sum(
        row.amount for row in rows
        if row.direction == "DEBIT" and row.status in {
            "COMPLETED", "PENDING_DISPENSE", "DISPENSE_FAILED", "REVERSED"
        }
    )
    return credits, debits


def assert_invariant(factory, member_id):
    with factory() as session:
        member = session.get(Member, member_id)
        credits, debits = ledger_sums(session, member_id)
        assert member.balance == credits - debits
        assert member.balance >= 0


def test_debit_success(db):
    _, factory = db
    member_id = add_member(factory)
    with factory() as session:
        row = debit(LedgerService(session), member_id)
        assert row.direction == "DEBIT"
        assert row.amount == 5_000
    with factory() as session:
        assert session.get(Member, member_id).balance == 5_000
        assert session.scalar(
            select(Transaction).where(Transaction.member_id == member_id)
        ) is not None
    assert_invariant(factory, member_id)


def test_debit_insufficient(db):
    _, factory = db
    member_id = add_member(factory, balance=5_000)
    with factory() as session, pytest.raises(InsufficientBalance):
        debit(LedgerService(session), member_id, 6_000)
    with factory() as session:
        assert session.get(Member, member_id).balance == 5_000
        assert session.scalar(select(Transaction.id)) is None


def test_debit_idempotent_same_payload(db):
    _, factory = db
    member_id = add_member(factory)
    with factory() as session:
        debit(LedgerService(session), member_id)
    with factory() as session, pytest.raises(IdempotencyConflict) as exc:
        debit(LedgerService(session), member_id)
    assert exc.value.original is not None
    assert exc.value.conflict is False
    assert exc.value.original.txn_uuid == "debit-1"


def test_debit_idempotent_diff_payload(db):
    _, factory = db
    member_id = add_member(factory)
    with factory() as session:
        debit(LedgerService(session), member_id)
    with factory() as session, pytest.raises(IdempotencyConflict) as exc:
        debit(LedgerService(session), member_id, 4_000)
    assert exc.value.original is None
    assert exc.value.conflict is True


def test_credit_success_and_idempotency(db):
    _, factory = db
    member_id = add_member(factory, balance=0)
    with factory() as session:
        row = LedgerService(session).credit(
            member_id, 7_000, txn_uuid="topup-1", type="TOPUP",
            source="ADMIN", performed_by_type="ADMIN", performed_by_id="1",
        )
        assert row.direction == "CREDIT"
    with factory() as session, pytest.raises(IdempotencyConflict) as exc:
        LedgerService(session).credit(
            member_id, 7_000, txn_uuid="topup-1", type="TOPUP",
            source="ADMIN", performed_by_type="ADMIN", performed_by_id="1",
        )
    assert exc.value.original is not None
    with factory() as session:
        assert session.get(Member, member_id).balance == 7_000
    assert_invariant(factory, member_id)


def test_credit_idempotency_conflict(db):
    _, factory = db
    member_id = add_member(factory, balance=0)
    with factory() as session:
        LedgerService(session).credit(
            member_id, 7_000, txn_uuid="topup-2", performed_by_type="ADMIN"
        )
    with factory() as session, pytest.raises(IdempotencyConflict) as exc:
        LedgerService(session).credit(
            member_id, 8_000, txn_uuid="topup-2", performed_by_type="ADMIN"
        )
    assert exc.value.conflict is True


def test_reverse_completed_debit(db):
    _, factory = db
    member_id = add_member(factory)
    with factory() as session:
        original = debit(LedgerService(session), member_id)
        original_id = original.id
    with factory() as session:
        reversal = LedgerService(session).reverse(
            original_id, reason="Test reversal",
            performed_by_type="ADMIN", performed_by_id="1",
        )
        assert reversal.type == "ADJUSTMENT"
        assert reversal.direction == "CREDIT"
        assert reversal.ref_txn_id == original_id
    with factory() as session:
        assert session.get(Member, member_id).balance == 10_000
        assert session.get(Transaction, original_id).status == "COMPLETED"
    assert_invariant(factory, member_id)


def test_concurrent_debits_no_overspend(db):
    _, factory = db
    member_id = add_member(factory, balance=10_000)
    barrier = threading.Barrier(10)

    def worker(index):
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                debit(
                    LedgerService(session), member_id, 2_000,
                    txn_uuid=f"parallel-{index}",
                )
                return "success"
            except InsufficientBalance:
                return "insufficient"

    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(worker, range(10)))
    succeeded = outcomes.count("success")
    failed = outcomes.count("insufficient")
    with factory() as session:
        final_balance = session.get(Member, member_id).balance
    assert succeeded == 5
    assert failed == 5
    assert final_balance == 0
    assert_invariant(factory, member_id)


def test_ledger_invariant_after_random_ops(db, monkeypatch):
    _, factory = db
    member_ids = [add_member(factory, balance=20_000, suffix=i) for i in range(1, 6)]
    rng = random.Random(20261105)
    reversible = {member_id: [] for member_id in member_ids}

    for index in range(20):
        member_id = rng.choice(member_ids)
        with factory() as session:
            service = LedgerService(session)
            operation = rng.choice(("credit", "debit", "reverse"))
            if operation == "credit":
                service.credit(
                    member_id, rng.randint(100, 2_000), txn_uuid=f"random-credit-{index}",
                    performed_by_type="ADMIN", performed_by_id="1",
                )
            elif operation == "debit":
                try:
                    row = debit(
                        service, member_id, rng.randint(100, 2_000),
                        txn_uuid=f"random-debit-{index}",
                    )
                    reversible[member_id].append(row.id)
                except InsufficientBalance:
                    pass
            elif reversible[member_id]:
                txn_id = reversible[member_id].pop()
                service.reverse(
                    txn_id, reason="Randomized test",
                    performed_by_type="ADMIN", performed_by_id="1",
                )
        assert_invariant(factory, member_id)

    from app import cli

    monkeypatch.setattr(cli, "SessionLocal", factory)
    output = StringIO()
    with redirect_stdout(output):
        assert cli.verify_ledger() == 0
    assert "OK: 5 members verified" in output.getvalue()


def test_negative_balance_db_rejected(db):
    engine, factory = db
    member_id = add_member(factory)
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text("UPDATE members SET balance = -1 WHERE id = :member_id"),
            {"member_id": member_id},
        )
