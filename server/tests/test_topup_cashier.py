"""Cashier top-up API, lockout, idempotency, audit and allowance tests."""
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import db
from app.main import app
from app.models import (
    AuditLog,
    Base,
    Card,
    Device,
    Member,
    OfflineAllowance,
    Operator,
    OperatorDevice,
    TopUpRequest,
    Transaction,
)
from app.security.device_token import generate_device_token, hash_device_token
from app.security.operator_pin import hash_operator_pin
from app.security.pins import hash_pin


@pytest.fixture
def topup_env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'topups.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", factory)
    tokens = {"CSH-001": generate_device_token(), "VND-001": generate_device_token()}
    with factory.begin() as session:
        cashier = Device(device_id="CSH-001", name="Cashier", type="cashier", token_hash=hash_device_token(tokens["CSH-001"]), status="ACTIVE", config_json='{"offline_enabled":true}')
        vending = Device(device_id="VND-001", name="Vending", type="vending", token_hash=hash_device_token(tokens["VND-001"]), status="ACTIVE", config_json='{"offline_enabled":true}')
        session.add_all([cashier, vending])
        session.flush()
        member = Member(member_code="MG-A00001", full_name="Member Test", nik_enc="enc", nik_idx="idx", balance=10_000, status="ACTIVE")
        session.add(member)
        session.flush()
        session.add(Card(member_id=member.id, uid="A1B2C3D4", pin_hash=hash_pin("4610"), status="ACTIVE"))
        operator = Operator(operator_no=1, nama="Operator Satu", operator_pin_hash=hash_operator_pin("918273"), is_active=True)
        session.add(operator)
        session.flush()
        session.add(OperatorDevice(operator_id=operator.id, device_id=cashier.id))
        session.add_all([
            OfflineAllowance(member_id=member.id, device_id=cashier.id, amount=5_000, computed_at=datetime.now(UTC), version=1),
            OfflineAllowance(member_id=member.id, device_id=vending.id, amount=5_000, computed_at=datetime.now(UTC), version=1),
        ])
    with TestClient(app) as client:
        yield {"client": client, "factory": factory, "tokens": tokens}
    engine.dispose()


def headers(env, device="CSH-001"):
    return {"Authorization": f"Bearer {env['tokens'][device]}", "X-Device-Id": device}


def body(**overrides):
    value = {"txn_uuid": "topup-0001", "uid": "A1B2C3D4", "amount": 5_000, "operator_no": 1, "operator_pin": "918273", "pin": "4610", "ts": int(time.time())}
    value.update(overrides)
    return value


def post(env, **overrides):
    return env["client"].post("/api/v1/topups", json=body(**overrides), headers=headers(env))


def test_topup_success(topup_env):
    response = post(topup_env)
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["balance_before"], data["balance_after"], data["status"]) == (10_000, 15_000, "COMPLETED")
    with topup_env["factory"]() as session:
        assert session.scalar(select(Member.balance)) == 15_000
        assert session.scalar(select(TopUpRequest)).source == "CASHIER"
        assert session.scalar(select(Transaction).where(Transaction.type == "TOPUP")).source == "CASHIER"
        assert session.scalar(select(AuditLog).where(AuditLog.action == "topup.cashier")) is not None
        assert sum(r.amount for r in session.scalars(select(OfflineAllowance)).all()) <= 15_000


def test_topup_member_pin_wrong(topup_env):
    response = post(topup_env, pin="9999")
    assert response.json()["error"]["code"] == "INVALID_PIN"
    assert response.json()["error"]["details"]["attempts_left"] == 2
    with topup_env["factory"]() as session:
        assert session.scalar(select(Card)).pin_fail_count == 1
        assert session.scalar(select(TopUpRequest)) is None


def test_topup_operator_pin_wrong(topup_env):
    response = post(topup_env, operator_pin="111111")
    assert response.json()["error"]["code"] == "OPERATOR_INVALID"
    with topup_env["factory"]() as session:
        assert session.scalar(select(Operator)).pin_fail_count == 1
        assert session.scalar(select(TopUpRequest)) is None


def test_topup_operator_5_wrong_locks_15min(topup_env):
    for _ in range(5):
        response = post(topup_env, operator_pin="654321")
    assert response.json()["error"]["code"] == "OPERATOR_LOCKED"
    with topup_env["factory"]() as session:
        operator = session.scalar(select(Operator))
        assert operator.locked_until is not None
        assert timedelta(minutes=14, seconds=50) <= operator.locked_until.replace(tzinfo=UTC) - datetime.now(UTC) <= timedelta(minutes=15, seconds=5)
    assert post(topup_env).json()["error"]["code"] == "OPERATOR_LOCKED"


def test_topup_operator_unbound(topup_env):
    with topup_env["factory"].begin() as session:
        session.query(OperatorDevice).delete()
    response = post(topup_env)
    assert response.json()["error"]["code"] == "OPERATOR_INVALID"


def test_topup_wrong_device_type(topup_env):
    response = topup_env["client"].post("/api/v1/topups", json=body(), headers=headers(topup_env, "VND-001"))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_topup_amount_not_multiple_of_1000(topup_env):
    assert post(topup_env, amount=5_500).json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("amount", [4_000, 1_001_000])
def test_topup_amount_limits(topup_env, amount):
    assert post(topup_env, amount=amount).json()["error"]["code"] == "VALIDATION_ERROR"


def test_topup_duplicate_same_payload(topup_env):
    first = post(topup_env)
    second = topup_env["client"].post("/api/v1/topups", json=body(), headers=headers(topup_env))
    assert first.status_code == second.status_code == 200
    with topup_env["factory"]() as session:
        assert session.scalar(select(Member.balance)) == 15_000
        assert len(session.scalars(select(TopUpRequest)).all()) == 1


def test_topup_duplicate_diff_payload(topup_env):
    assert post(topup_env).status_code == 200
    response = post(topup_env, amount=6_000)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_TXN"


def test_topup_clock_skew(topup_env):
    assert post(topup_env, ts=1).json()["error"]["code"] == "CLOCK_SKEW"


def test_topup_requires_device_auth(topup_env):
    response = topup_env["client"].post("/api/v1/topups", json=body())
    assert response.status_code == 401


def test_topup_recomputes_allowances(topup_env):
    assert post(topup_env).status_code == 200
    with topup_env["factory"]() as session:
        rows = session.scalars(select(OfflineAllowance)).all()
        assert len(rows) == 2
        assert all(row.amount <= 7_500 for row in rows)


def test_topup_creates_audit_log(topup_env):
    assert post(topup_env).status_code == 200
    with topup_env["factory"]() as session:
        logs = session.scalars(select(AuditLog).where(AuditLog.action == "topup.cashier")).all()
        assert len(logs) == 1
