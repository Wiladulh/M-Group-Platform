"""Cashier payment, balance-check, isolation, and redaction API tests."""

from contextlib import redirect_stdout
from io import StringIO

import pytest
from app import cli, db
from app.main import app
from app.models import AuditLog, Base, Card, Device, Member, OfflineAllowance, Transaction
from app.security.device_token import generate_device_token, hash_device_token
from app.security.pins import hash_pin
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def cashier(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'payments.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", factory)
    tokens = {"CSH-001": generate_device_token(), "CSH-002": generate_device_token()}
    with factory.begin() as session:
        member = Member(
            member_code="MG-A00001",
            full_name="Member Test",
            nik_enc="encrypted-test",
            nik_idx="blind-index-test",
            balance=0,
            status="ACTIVE",
        )
        session.add(member)
        session.flush()
        member_id = member.id
        session.add(
            Card(
                member_id=member_id,
                uid="A1B2C3D4",
                pin_hash=hash_pin("4610"),
                pin_fail_count=0,
                status="ACTIVE",
            )
        )
        for device_id, token in tokens.items():
            session.add(
                Device(
                    device_id=device_id,
                    name=device_id,
                    type="cashier",
                    reported_mode="manual",
                    slot_count=0,
                    token_hash=hash_device_token(token),
                    status="ACTIVE",
                    config_json='{"offline_enabled":true,"offline_card_cap":50000}',
                )
            )
    with factory() as session:
        from app.services.ledger import LedgerService

        LedgerService(session).credit(
            member_id,
            20_000,
            txn_uuid="opening-payment-test",
            type="TOPUP",
            source="ADMIN",
            performed_by_type="SYSTEM",
            performed_by_id="TEST",
        )
    monkeypatch.setattr(cli, "SessionLocal", factory)
    with TestClient(app) as client:
        yield {
            "client": client,
            "factory": factory,
            "engine": engine,
            "tokens": tokens,
            "member_id": member_id,
        }
    engine.dispose()


def headers(cashier, device_id="CSH-001"):
    return {
        "Authorization": f"Bearer {cashier['tokens'][device_id]}",
        "X-Device-Id": device_id,
    }


def payment_body(**overrides):
    body = {
        "txn_uuid": "pay-0001",
        "uid": "A1B2C3D4",
        "amount": 5_000,
        "ts": __import__("time").time_ns() // 1_000_000_000,
        "pin": "4610",
    }
    body.update(overrides)
    return body


def balance_body(**overrides):
    body = {
        "uid": "A1B2C3D4",
        "pin": "4610",
        "ts": __import__("time").time_ns() // 1_000_000_000,
    }
    body.update(overrides)
    return body


def post_payment(cashier, **overrides):
    return cashier["client"].post(
        "/api/v1/payments", json=payment_body(**overrides), headers=headers(cashier)
    )


def card_row(cashier):
    with cashier["factory"]() as session:
        return session.scalar(select(Card))


def test_payment_success_online(cashier):
    response = post_payment(cashier)
    assert response.status_code == 200
    data = response.json()
    assert (data["balance_before"], data["balance_after"]) == (20_000, 15_000)
    assert data["status"] == "COMPLETED"
    with cashier["factory"]() as session:
        assert session.scalar(
            select(Transaction.id).where(Transaction.txn_uuid == "pay-0001")
        ) is not None
        assert session.scalar(
            select(Member.balance).where(Member.id == cashier["member_id"])
        ) == 15_000
    output = StringIO()
    with redirect_stdout(output):
        assert cli.verify_ledger() == 0
    assert "OK: 1 members verified" in output.getvalue()



def test_verify_ledger_after_three_successful_payments(cashier):
    for index in range(3):
        response = post_payment(
            cashier,
            txn_uuid=f"three-payments-{index}",
            amount=1_000,
        )
        assert response.status_code == 200
    output = StringIO()
    with redirect_stdout(output):
        assert cli.verify_ledger() == 0
    assert output.getvalue().strip() == "OK: 1 members verified"

def test_payment_pin_wrong_attempts_left(cashier):
    response = post_payment(cashier, pin="9999")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PIN"
    assert response.json()["error"]["details"]["attempts_left"] == 2
    assert card_row(cashier).pin_fail_count == 1


def test_payment_three_wrong_pins_locks(cashier):
    for index in range(3):
        response = post_payment(cashier, txn_uuid=f"wrong-{index}", pin="9999")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CARD_LOCKED"
    card = card_row(cashier)
    assert card.status == "LOCKED"
    assert card.pin_fail_count == 3


def test_payment_insufficient_balance(cashier):
    response = post_payment(cashier, amount=25_000)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    with cashier["factory"]() as session:
        assert session.scalar(
            select(Transaction.id).where(Transaction.txn_uuid == "pay-0001")
        ) is None


def test_payment_clock_skew(cashier):
    response = post_payment(cashier, ts=1)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CLOCK_SKEW"


def test_payment_card_unknown(cashier):
    response = post_payment(cashier, uid="11223344")
    assert response.json()["error"]["code"] == "CARD_UNKNOWN"


@pytest.mark.parametrize(("status", "code"), [("LOCKED", "CARD_LOCKED"), ("INACTIVE", "CARD_INACTIVE")])
def test_payment_card_status(cashier, status, code):
    with cashier["factory"].begin() as session:
        session.scalar(select(Card)).status = status
    response = post_payment(cashier)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_payment_member_suspended(cashier):
    with cashier["factory"].begin() as session:
        session.scalar(select(Member)).status = "SUSPENDED"
    response = post_payment(cashier)
    assert response.json()["error"]["code"] == "MEMBER_SUSPENDED"


def test_payment_duplicate_same_payload(cashier):
    body = payment_body()
    first = cashier["client"].post("/api/v1/payments", json=body, headers=headers(cashier))
    second = cashier["client"].post("/api/v1/payments", json=body, headers=headers(cashier))
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    with cashier["factory"]() as session:
        assert session.scalar(select(Member.balance)) == 15_000
        assert len(session.scalars(select(Transaction).where(Transaction.type == "PAYMENT")).all()) == 1


def test_payment_duplicate_diff_payload(cashier):
    assert post_payment(cashier).status_code == 200
    response = post_payment(cashier, amount=4_000)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_TXN"


def test_payment_requires_device_auth(cashier):
    response = cashier["client"].post("/api/v1/payments", json=payment_body())
    assert response.status_code == 401


def test_balance_check_success(cashier):
    response = cashier["client"].post(
        "/api/v1/balance-check", json=balance_body(), headers=headers(cashier)
    )
    assert response.status_code == 200
    assert response.json()["balance"] == 20_000
    with cashier["factory"]() as session:
        assert session.scalar(select(Transaction.id).where(Transaction.type == "PAYMENT")) is None
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "balance_check"))
        assert audit is not None
        assert audit.actor_type == "DEVICE"
        assert audit.before_json is audit.after_json is None


def test_balance_check_wrong_pin_counts_toward_lockout(cashier):
    for _ in range(2):
        response = cashier["client"].post(
            "/api/v1/balance-check",
            json=balance_body(pin="9999"),
            headers=headers(cashier),
        )
        assert response.json()["error"]["code"] == "INVALID_PIN"
    response = post_payment(cashier, pin="9999")
    assert response.json()["error"]["code"] == "CARD_LOCKED"
    assert card_row(cashier).pin_fail_count == 3


def test_get_transaction_own_device_200(cashier):
    assert post_payment(cashier).status_code == 200
    response = cashier["client"].get(
        "/api/v1/transactions/pay-0001", headers=headers(cashier)
    )
    assert response.status_code == 200
    assert response.json()["direction"] == "DEBIT"


def test_get_transaction_other_device_404(cashier):
    assert post_payment(cashier).status_code == 200
    response = cashier["client"].get(
        "/api/v1/transactions/pay-0001", headers=headers(cashier, "CSH-002")
    )
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Transaksi tidak ditemukan"


def test_get_transaction_not_found_404(cashier):
    response = cashier["client"].get(
        "/api/v1/transactions/no-such-txn", headers=headers(cashier)
    )
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Transaksi tidak ditemukan"


def test_error_messages_indonesian():
    from app.errors import ERROR_MESSAGES, DomainError

    expected = {
        "INSUFFICIENT_BALANCE": "Saldo tidak cukup",
        "INVALID_PIN": "PIN salah. Sisa percobaan: 2",
        "CARD_LOCKED": "Kartu terkunci. Hubungi admin",
        "CARD_INACTIVE": "Kartu tidak aktif",
        "CARD_UNKNOWN": "Kartu tidak terdaftar",
        "MEMBER_SUSPENDED": "Member nonaktif",
        "CLOCK_SKEW": "Jam perangkat tidak sinkron. Hubungi admin.",
    }
    for code, message in expected.items():
        details = {"attempts_left": 2} if code == "INVALID_PIN" else {}
        assert DomainError(code=code, details=details).rendered_message == message
    assert ERROR_MESSAGES["DUPLICATE_TXN"] == "Transaksi duplikat"


def test_payment_recomputes_allowance(cashier):
    response = post_payment(cashier)
    assert response.status_code == 200
    with cashier["factory"]() as session:
        rows = session.scalars(
            select(OfflineAllowance).where(OfflineAllowance.member_id == cashier["member_id"])
        ).all()
        assert len(rows) == 2
        assert {row.amount for row in rows} == {7_500}


def test_logs_do_not_contain_secrets(cashier, caplog):
    token = cashier["tokens"]["CSH-001"]
    response = post_payment(cashier)
    assert response.status_code == 200
    assert "4610" not in caplog.text
    assert token not in caplog.text


def test_device_config_route_remains_available(cashier):
    response = cashier["client"].get("/api/v1/device/config", headers=headers(cashier))
    assert response.status_code == 200
    assert response.json()["device_id"] == "CSH-001"
