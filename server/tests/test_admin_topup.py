"""Admin top-up creation, reversal, idempotency and audit tests."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.errors import DomainError
from app.models import AdminUser, AuditLog, Base, Member, TopUpRequest, Transaction
from app.security.passwords import hash_password
from app.services.admin_topup import AdminTopupService
from app.services.ledger import LedgerService


@pytest.fixture
def admin_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'admin-topup.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            AdminUser(
                id=1,
                username="admin",
                display_name="Administrator",
                password_hash=hash_password("ci-password-123"),
                must_change_password=False,
            )
        )
        session.add(
            Member(
                member_code="MG-A00001",
                full_name="Member Test",
                nik_enc="enc",
                nik_idx="idx",
                balance=0,
                status="ACTIVE",
            )
        )
    with factory() as session:
        member_id = session.scalar(select(Member.id))
    yield engine, factory, member_id
    engine.dispose()


def create_service(factory):
    return AdminTopupService(factory())


def test_admin_topup_success(admin_db):
    _engine, factory, member_id = admin_db
    row = create_service(factory).create_topup(
        member_id, 5_000, request_uuid="admin-topup-1", note="Kasir tutup",
        performed_by_admin_id=1, ip="127.0.0.1",
    )
    with factory() as session:
        assert session.get(Member, member_id).balance == 5_000
        assert row.source == "ADMIN"
        assert session.scalar(select(TopUpRequest)).status == "COMPLETED"
        assert session.scalar(select(Transaction).where(Transaction.type == "TOPUP")).source == "ADMIN"


def test_admin_topup_idempotent(admin_db):
    _engine, factory, member_id = admin_db
    service = create_service(factory)
    first = service.create_topup(member_id, 5_000, request_uuid="same-key", note=None, performed_by_admin_id=1, ip=None)
    second = service.create_topup(member_id, 5_000, request_uuid="same-key", note=None, performed_by_admin_id=1, ip=None)
    assert first.id == second.id
    with factory() as session:
        assert session.get(Member, member_id).balance == 5_000
        assert len(session.scalars(select(TopUpRequest)).all()) == 1


def test_admin_topup_diff_payload_same_uuid(admin_db):
    _engine, factory, member_id = admin_db
    service = create_service(factory)
    service.create_topup(member_id, 5_000, request_uuid="same-key", note=None, performed_by_admin_id=1, ip=None)
    with pytest.raises(DomainError) as exc:
        service.create_topup(member_id, 6_000, request_uuid="same-key", note=None, performed_by_admin_id=1, ip=None)
    assert exc.value.code == "DUPLICATE_TXN"


def test_admin_topup_inactive_member(admin_db):
    _engine, factory, member_id = admin_db
    with factory.begin() as session:
        session.get(Member, member_id).status = "SUSPENDED"
    with pytest.raises(DomainError) as exc:
        create_service(factory).create_topup(member_id, 5_000, request_uuid="inactive", note=None, performed_by_admin_id=1, ip=None)
    assert exc.value.code == "MEMBER_SUSPENDED"


def test_admin_topup_invalid_amount(admin_db):
    _engine, factory, member_id = admin_db
    with pytest.raises(DomainError) as exc:
        create_service(factory).create_topup(member_id, 5_500, request_uuid="bad-amount", note=None, performed_by_admin_id=1, ip=None)
    assert exc.value.code == "VALIDATION_ERROR"


def test_admin_topup_reverse_success(admin_db):
    _engine, factory, member_id = admin_db
    service = create_service(factory)
    row = service.create_topup(member_id, 5_000, request_uuid="reverse-key", note=None, performed_by_admin_id=1, ip=None)
    reversed_row = service.reverse_topup(row.id, reason="Salah input", performed_by_admin_id=1, ip=None)
    with factory() as session:
        member = session.get(Member, member_id)
        original = session.get(TopUpRequest, row.id)
        reversal = session.get(Transaction, reversed_row.reversal_txn_id)
        assert member.balance == 0
        assert original.status == "REVERSED"
        assert original.reversal_txn_id == reversal.id
        assert original.reverse_reason == "Salah input"
        assert reversal.type == "ADJUSTMENT"
        assert reversal.direction == "DEBIT"
        assert reversal.ref_txn_id == original.txn_id


def test_admin_topup_reverse_insufficient_balance(admin_db):
    _engine, factory, member_id = admin_db
    service = create_service(factory)
    row = service.create_topup(member_id, 5_000, request_uuid="spent-key", note=None, performed_by_admin_id=1, ip=None)
    with factory() as session:
        LedgerService(session).debit(
            member_id, 5_000, txn_uuid="spend-key", card_id=None, device_id=None,
            type="PAYMENT", source="ONLINE", performed_by_type="DEVICE", performed_by_id="CSH-001",
        )
    with pytest.raises(DomainError) as exc:
        service.reverse_topup(row.id, reason="Salah input", performed_by_admin_id=1, ip=None)
    assert exc.value.code == "REVERSE_INSUFFICIENT"
    with factory() as session:
        assert session.get(TopUpRequest, row.id).status == "COMPLETED"
        assert session.scalar(select(Transaction).where(Transaction.ref_txn_id == row.txn_id)) is None


def test_admin_topup_reverse_already_reversed(admin_db):
    _engine, factory, member_id = admin_db
    service = create_service(factory)
    row = service.create_topup(member_id, 5_000, request_uuid="double-key", note=None, performed_by_admin_id=1, ip=None)
    service.reverse_topup(row.id, reason="Salah input", performed_by_admin_id=1, ip=None)
    with pytest.raises(DomainError) as exc:
        service.reverse_topup(row.id, reason="Kedua", performed_by_admin_id=1, ip=None)
    assert exc.value.code == "VALIDATION_ERROR"


def test_admin_topup_reverse_requires_reason(admin_db):
    _engine, factory, member_id = admin_db
    service = create_service(factory)
    row = service.create_topup(member_id, 5_000, request_uuid="empty-reason", note=None, performed_by_admin_id=1, ip=None)
    with pytest.raises(DomainError) as exc:
        service.reverse_topup(row.id, reason="", performed_by_admin_id=1, ip=None)
    assert exc.value.code == "VALIDATION_ERROR"


def test_admin_topup_audit_log(admin_db):
    _engine, factory, member_id = admin_db
    service = create_service(factory)
    row = service.create_topup(member_id, 5_000, request_uuid="audit-key", note=None, performed_by_admin_id=1, ip=None)
    service.reverse_topup(row.id, reason="Koreksi", performed_by_admin_id=1, ip=None)
    with factory() as session:
        actions = set(session.scalars(select(AuditLog.action)).all())
        assert {"topup.admin", "topup.reverse"} <= actions
