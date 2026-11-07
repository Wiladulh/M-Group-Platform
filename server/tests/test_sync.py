"""Offline sync service regression tests, including rejected ledger rows."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, Card, Device, Member, OfflineAllowance, PendingSyncLog,
    ShortfallRecord, Transaction,
)
from app.schemas.sync import SyncBatch, SyncItem
from app.security.pins import hash_pin
from app.services.ledger import LedgerService
from app.services.sync import SyncService


@pytest.fixture
def sync_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sync.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        member = Member(
            member_code="MG-A00001", full_name="Sync Member",
            nik_enc="enc", nik_idx="idx", balance=0, status="ACTIVE",
        )
        session.add(member)
        session.flush()
        member_id = member.id
    with factory() as session:
        LedgerService(session).credit(
            member_id, 10_000, txn_uuid="sync-opening-balance",
            type="TOPUP", source="ADMIN",
            performed_by_type="SYSTEM", performed_by_id="TEST",
        )
    with factory.begin() as session:
        device = Device(
            device_id="CSH-001", name="Cashier 001", type="cashier",
            token_hash="c" * 64, status="ACTIVE", slot_count=0,
            config_json='{"offline_enabled":true}',
        )
        session.add(device)
        session.flush()
        card = Card(
            member_id=member_id, uid="A1B2C3D4",
            pin_hash=hash_pin("4610"), status="ACTIVE",
        )
        session.add(card)
        session.flush()
        session.add(OfflineAllowance(
            member_id=member_id, device_id=device.id, amount=10_000,
            computed_at=datetime.now(UTC), version=1,
        ))
        device_id, card_id = device.id, card.id
    yield engine, factory, device_id, member_id, card_id
    engine.dispose()


def _batch(txn_uuid="offline-txn-1", *, price=5_000, offline_ts=None,
           uid="A1B2C3D4", dispense_result=None, pin_fail_events=0,
           batch_uuid="batch-1"):
    return SyncBatch(
        batch_uuid=batch_uuid,
        items=[SyncItem(
            txn_uuid=txn_uuid, uid=uid, slot_no=None, product_id=None,
            manual_amount=None, price=price,
            offline_ts=offline_ts or int(datetime.now(UTC).timestamp()) - 5,
            ts_untrusted=None, dispense_result=dispense_result,
            pin_fail_events=pin_fail_events,
        )],
    )


def test_sync_single_offline_payment_accepted(sync_db):
    _, factory, device_id, member_id, _ = sync_db
    with factory() as session:
        device = SimpleNamespace(id=device_id, device_id="CSH-001", type="cashier")
        result = SyncService(session).process_batch(device, _batch())
        assert result.accepted == 1
        assert result.rejected == 0
    with factory() as session:
        txn = session.scalar(select(Transaction).where(Transaction.txn_uuid == "offline-txn-1"))
        assert txn.source == "OFFLINE_SYNC"
        assert txn.status == "COMPLETED"
        assert txn.balance_before == 10_000
        assert txn.balance_after == 5_000
        assert session.get(Member, member_id).balance == 5_000
        log = session.scalar(select(PendingSyncLog).where(PendingSyncLog.batch_uuid == "batch-1"))
        assert log.total == 1 and log.accepted == 1


def test_sync_insufficient_creates_shortfall(sync_db, monkeypatch):
    _, factory, device_id, member_id, _ = sync_db
    with factory() as session:
        LedgerService(session).debit(
            member_id, 5_000, txn_uuid="sync-pretest-debit",
            card_id=None, device_id=None, type="PAYMENT", source="ONLINE",
            performed_by_type="DEVICE", performed_by_id="TEST",
        )
    with factory() as session:
        device = SimpleNamespace(id=device_id, device_id="CSH-001", type="cashier")
        response = SyncService(session).process_batch(
            device, _batch(price=8_000, txn_uuid="shortfall-txn")
        )
        assert response.rejected == 1
        assert response.results[0].reason == "INSUFFICIENT_AT_SYNC"
        assert response.results[0].shortfall_id is not None
    with factory() as session:
        txn = session.scalar(select(Transaction).where(Transaction.txn_uuid == "shortfall-txn"))
        shortfall = session.scalar(
            select(ShortfallRecord).where(ShortfallRecord.txn_uuid == "shortfall-txn")
        )
        assert txn is not None and txn.status == "REJECTED"
        assert txn.reject_reason == "INSUFFICIENT_AT_SYNC"
        assert txn.balance_before == txn.balance_after == 5_000
        assert txn.amount == 8_000
        assert shortfall is not None and shortfall.status == "OPEN"
        assert session.get(Member, member_id).balance == 5_000

    from app import cli
    monkeypatch.setattr(cli, "SessionLocal", factory)
    assert cli.verify_ledger() == 0


def test_sync_rejected_txn_row_created(sync_db):
    _, factory, device_id, member_id, _ = sync_db
    with factory() as session:
        LedgerService(session).debit(
            member_id, 5_000, txn_uuid="rejected-seed-debit",
            card_id=None, device_id=None, type="PAYMENT", source="ONLINE",
            performed_by_type="DEVICE", performed_by_id="TEST",
        )
    with factory() as session:
        device = SimpleNamespace(id=device_id, device_id="CSH-001", type="cashier")
        SyncService(session).process_batch(device, _batch(price=8_000, txn_uuid="rejected-row"))
    with factory() as session:
        row = session.scalar(select(Transaction).where(Transaction.txn_uuid == "rejected-row"))
        shortfall = session.scalar(select(ShortfallRecord).where(ShortfallRecord.txn_uuid == "rejected-row"))
        assert row.status == "REJECTED"
        assert row.reject_reason == "INSUFFICIENT_AT_SYNC"
        assert row.balance_before == row.balance_after == 5_000
        assert row.amount == 8_000
        assert shortfall is not None
        assert session.get(Member, member_id).balance == 5_000


def test_sync_unknown_card_no_shortfall(sync_db):
    _, factory, device_id, _member_id, _ = sync_db
    with factory() as session:
        device = SimpleNamespace(id=device_id, device_id="CSH-001", type="cashier")
        response = SyncService(session).process_batch(
            device, _batch(uid="FFFFFFFF", txn_uuid="unknown-card-txn")
        )
        assert response.results[0].reason == "CARD_UNKNOWN"
    with factory() as session:
        assert session.scalar(
            select(Transaction).where(Transaction.txn_uuid == "unknown-card-txn")
        ) is None
        assert session.scalar(
            select(ShortfallRecord).where(ShortfallRecord.txn_uuid == "unknown-card-txn")
        ) is None
        log = session.scalar(select(PendingSyncLog).where(PendingSyncLog.batch_uuid == "batch-1"))
        detail = json.loads(log.detail_json)
        assert detail["items"][0]["uid"] == "FFFFFFFF"


def test_sync_idempotent_same_txn_uuid(sync_db):
    _, factory, device_id, member_id, _ = sync_db
    with factory() as session:
        device = session.get(Device, device_id)
        SyncService(session).process_batch(device, _batch(batch_uuid="first-batch"))
    with factory() as session:
        device = session.get(Device, device_id)
        response = SyncService(session).process_batch(device, _batch(batch_uuid="second-batch"))
        assert response.results[0].status == "DUPLICATE"
    with factory() as session:
        assert session.get(Member, member_id).balance == 5_000


def test_sync_batch_idempotent_same_batch_uuid(sync_db):
    _, factory, device_id, member_id, _ = sync_db
    with factory() as session:
        device = session.get(Device, device_id)
        SyncService(session).process_batch(device, _batch())
    with factory() as session:
        device = session.get(Device, device_id)
        response = SyncService(session).process_batch(device, _batch())
        assert response.results[0].status == "DUPLICATE"
    with factory() as session:
        assert session.get(Member, member_id).balance == 5_000
        assert len(session.scalars(select(Transaction).where(
            Transaction.txn_uuid == "offline-txn-1"
        )).all()) == 1


def test_sync_duplicate_payload_conflict(sync_db):
    _, factory, device_id, _member_id, _ = sync_db
    with factory() as session:
        device = session.get(Device, device_id)
        SyncService(session).process_batch(device, _batch(batch_uuid="original"))
    with factory() as session:
        device = session.get(Device, device_id)
        response = SyncService(session).process_batch(
            device, _batch(price=4_000, batch_uuid="conflict")
        )
        assert response.results[0].status == "REJECTED"
        assert response.results[0].reason == "DUPLICATE_TXN_CONFLICT"


def test_sync_order_preserved(sync_db):
    _, factory, device_id, _member_id, _ = sync_db
    now = int(datetime.now(UTC).timestamp())
    batch = SyncBatch(batch_uuid="ordered-batch", items=[
        SyncItem(txn_uuid="ordered-3", uid="A1B2C3D4", price=1_000, offline_ts=now-1),
        SyncItem(txn_uuid="ordered-1", uid="A1B2C3D4", price=1_000, offline_ts=now-3),
        SyncItem(txn_uuid="ordered-2", uid="A1B2C3D4", price=1_000, offline_ts=now-2),
    ])
    with factory() as session:
        device = session.get(Device, device_id)
        SyncService(session).process_batch(device, batch)
    with factory() as session:
        rows = session.scalars(select(Transaction).where(
            Transaction.txn_uuid.in_(["ordered-1", "ordered-2", "ordered-3"])
        ).order_by(Transaction.created_at)).all()
        assert [row.txn_uuid for row in rows] == ["ordered-1", "ordered-2", "ordered-3"]


def test_sync_dispense_failed_triggers_refund(sync_db):
    _, factory, device_id, member_id, _ = sync_db
    with factory() as session:
        device = session.get(Device, device_id)
        SyncService(session).process_batch(
            device, _batch(dispense_result="failed", txn_uuid="failed-dispense")
        )
    with factory() as session:
        original = session.scalar(select(Transaction).where(
            Transaction.txn_uuid == "failed-dispense"
        ))
        refund = session.scalar(select(Transaction).where(
            Transaction.ref_txn_id == original.id
        ))
        assert original.status == "DISPENSE_FAILED"
        assert refund is not None and refund.type == "REFUND"
        assert session.get(Member, member_id).balance == 10_000


def test_sync_pin_fail_events_lockout(sync_db):
    _, factory, device_id, _member_id, card_id = sync_db
    with factory() as session:
        device = session.get(Device, device_id)
        response = SyncService(session).process_batch(
            device, _batch(pin_fail_events=3, txn_uuid="pin-fail-payment")
        )
        assert response.accepted == 1
    with factory() as session:
        assert session.get(Card, card_id).status == "LOCKED"


def test_sync_member_cache_version_increments(sync_db):
    _, factory, device_id, _member_id, _ = sync_db
    from app.services.cache_version import get_member_cache_version
    with factory() as session:
        before = get_member_cache_version(session)
    with factory() as session:
        device = session.get(Device, device_id)
        response = SyncService(session).process_batch(device, _batch())
        assert response.cache_version > before


def test_sync_returns_cache_delta(sync_db):
    _, factory, device_id, _member_id, _ = sync_db
    with factory() as session:
        device = session.get(Device, device_id)
        response = SyncService(session).process_batch(device, _batch())
        assert response.member_cache_delta
        assert response.member_cache_delta[0].balance_snapshot == 5_000


def test_sync_clock_skew_offline(sync_db):
    _, factory, device_id, member_id, _ = sync_db
    with factory() as session:
        device = session.get(Device, device_id)
        response = SyncService(session).process_batch(
            device, _batch(offline_ts=int(datetime.now(UTC).timestamp()) + 400)
        )
        assert response.results[0].reason == "CLOCK_SKEW_OFFLINE"
    with factory() as session:
        assert session.get(Member, member_id).balance == 10_000
        row = session.scalar(select(Transaction).where(Transaction.txn_uuid == "offline-txn-1"))
        assert row.status == "REJECTED"


def test_sync_batch_of_5_mixed(sync_db):
    _, factory, device_id, member_id, _ = sync_db
    now = int(datetime.now(UTC).timestamp()) - 5
    batch = SyncBatch(batch_uuid="mixed-five", items=[
        SyncItem(txn_uuid="mix-1", uid="A1B2C3D4", price=1_000, offline_ts=now),
        SyncItem(txn_uuid="mix-2", uid="A1B2C3D4", price=2_000, offline_ts=now + 1),
        SyncItem(txn_uuid="mix-3", uid="A1B2C3D4", price=3_000, offline_ts=now + 2),
        SyncItem(txn_uuid="mix-4", uid="A1B2C3D4", price=20_000, offline_ts=now + 3),
        SyncItem(txn_uuid="mix-5", uid="FFFFFFFF", price=1_000, offline_ts=now + 4),
    ])
    with factory() as session:
        device = SimpleNamespace(id=device_id, device_id="CSH-001", type="cashier")
        response = SyncService(session).process_batch(device, batch)
        assert (response.accepted, response.rejected, response.total) == (3, 2, 5)
    with factory() as session:
        assert session.get(Member, member_id).balance == 4_000
        log = session.scalar(select(PendingSyncLog).where(PendingSyncLog.batch_uuid == "mixed-five"))
        assert (log.total, log.accepted, log.rejected) == (5, 3, 2)


def test_verify_ledger_ignores_rejected(sync_db, monkeypatch):
    _, factory, _device_id, member_id, card_id = sync_db
    with factory.begin() as session:
        session.add(Transaction(
            txn_uuid="rejected-ledger-ignore",
            member_id=member_id,
            card_id=card_id,
            type="PAYMENT",
            amount=8_000,
            direction="DEBIT",
            balance_before=10_000,
            balance_after=10_000,
            status="REJECTED",
            reject_reason="INSUFFICIENT_AT_SYNC",
            source="OFFLINE_SYNC",
            occurred_at=datetime.now(UTC),
            performed_by_type="DEVICE",
            performed_by_id="CSH-001",
        ))
    from app import cli
    monkeypatch.setattr(cli, "SessionLocal", factory)
    assert cli.verify_ledger() == 0


def test_sync_card_inactive_at_sync_flag(sync_db):
    _, factory, device_id, _member_id, card_id = sync_db
    with factory.begin() as session:
        session.get(Card, card_id).status = "INACTIVE"
    with factory() as session:
        device = SimpleNamespace(id=device_id, device_id="CSH-001", type="cashier")
        SyncService(session).process_batch(
            device, _batch(txn_uuid="inactive-card-txn")
        )
    with factory() as session:
        txn = session.scalar(select(Transaction).where(
            Transaction.txn_uuid == "inactive-card-txn"
        ))
        assert txn.card_inactive_at_sync is True
        assert txn.status == "COMPLETED"


def test_sync_dispense_unknown_leaves_pending(sync_db):
    _, factory, device_id, _member_id, _ = sync_db
    with factory.begin() as session:
        vending = Device(
            device_id="VND-001", name="Vending 001", type="vending",
            token_hash="v" * 64, status="ACTIVE", slot_count=5,
            config_json='{"offline_enabled":true}',
        )
        session.add(vending)
        session.flush()
        vending_id = vending.id
    with factory() as session:
        device = SimpleNamespace(id=vending_id, device_id="VND-001", type="vending")
        SyncService(session).process_batch(
            device, _batch(txn_uuid="pending-dispense-txn", dispense_result="unknown")
        )
    with factory() as session:
        txn = session.scalar(select(Transaction).where(
            Transaction.txn_uuid == "pending-dispense-txn"
        ))
        assert txn.status == "PENDING_DISPENSE"


def test_sync_member_suspended_creates_rejected_row(sync_db):
    _, factory, device_id, member_id, _ = sync_db
    with factory.begin() as session:
        session.get(Member, member_id).status = "SUSPENDED"
    with factory() as session:
        device = SimpleNamespace(id=device_id, device_id="CSH-001", type="cashier")
        response = SyncService(session).process_batch(
            device, _batch(txn_uuid="suspended-member-txn")
        )
        assert response.results[0].reason == "MEMBER_SUSPENDED"
    with factory() as session:
        row = session.scalar(select(Transaction).where(
            Transaction.txn_uuid == "suspended-member-txn"
        ))
        assert row.status == "REJECTED"
        assert row.reject_reason == "MEMBER_SUSPENDED"
        assert row.balance_before == row.balance_after == 10_000


def test_batch_size_limit():
    from pydantic import ValidationError
    items = [
        SyncItem(
            txn_uuid=f"batch-limit-{index}", uid="A1B2C3D4",
            price=100, offline_ts=1,
        )
        for index in range(51)
    ]
    with pytest.raises(ValidationError):
        SyncBatch(batch_uuid="too-many", items=items)


def test_sync_requires_device_auth(client):
    response = client.get("/api/v1/device/member-cache?since=0")
    assert response.status_code == 401


def test_get_member_cache_since_version(sync_db):
    _, factory, device_id, _member_id, _ = sync_db
    device = SimpleNamespace(id=device_id, device_id="CSH-001", type="cashier")
    with factory() as session:
        SyncService(session).process_batch(device, _batch(txn_uuid="cache-endpoint-txn"))
    from app.routers.sync import get_member_cache
    with factory() as session:
        initial = get_member_cache(since=0, device=device, session=session)
        assert initial.entries
        current = initial.cache_version
    with factory() as session:
        unchanged = get_member_cache(since=current, device=device, session=session)
        assert unchanged.entries == []
        assert unchanged.cache_version == current
