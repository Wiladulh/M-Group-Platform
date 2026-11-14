"""HTTP tests for the administrator dashboard and database summaries."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuditLog, Base, Device, Member, Transaction
from app.services.admin_auth import create_admin_session


@pytest.fixture
def dashboard_client() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def dashboard_admin(dashboard_client):
    _, factory = dashboard_client
    db = factory()
    user = __import__("app.models", fromlist=["AdminUser"]).AdminUser(
        id=1,
        username="dashboard-admin",
        display_name="Dashboard Admin",
        password_hash=PasswordHasher().hash("CorrectHorseBatteryStaple!"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _authenticate(client: TestClient, factory, user) -> None:
    db = factory()
    token, _session = create_admin_session(db, user, "127.0.0.1", "pytest", 1440)
    db.commit()
    db.close()
    client.cookies.set(get_settings().session_cookie_name, token)


def test_dashboard_requires_login(dashboard_client):
    client, _ = dashboard_client
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_dashboard_renders(dashboard_client, dashboard_admin):
    client, factory = dashboard_client
    _authenticate(client, factory, dashboard_admin)
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "Recent Activity" in response.text
    assert "Device Status" in response.text


def test_dashboard_cards_show_database_values(dashboard_client, dashboard_admin):
    client, factory = dashboard_client
    db = factory()
    member = Member(
        member_code="MG-A0001",
        full_name="Test Member",
        nik_enc="encrypted-test-value",
        nik_idx="test-nik-index",
        balance=12345,
    )
    cashier = Device(
        device_id="CASHIER01",
        name="Cashier One",
        type="cashier",
        token_hash="a" * 64,
    )
    vending = Device(
        device_id="VENDING01",
        name="Vending One",
        type="vending",
        token_hash="b" * 64,
    )
    db.add_all([member, cashier, vending])
    db.flush()
    db.add(
        Transaction(
            txn_uuid="00000000-0000-4000-8000-000000000001",
            member_id=member.id,
            type="TOPUP",
            amount=5000,
            direction="CREDIT",
            balance_before=7345,
            balance_after=12345,
            status="COMPLETED",
            source="ADMIN",
            occurred_at=datetime.now(UTC).replace(tzinfo=None),
            performed_by_type="ADMIN",
        )
    )
    db.commit()
    db.close()
    _authenticate(client, factory, dashboard_admin)
    response = client.get("/admin")
    assert response.status_code == 200
    assert 'data-card="total-members">1<' in response.text
    assert "Rp 12,345" in response.text
    assert 'data-card="total-cashier">1<' in response.text
    assert 'data-card="total-vending">1<' in response.text
    assert 'data-card="transaksi-hari-ini">1<' in response.text
    assert "Rp 5,000" in response.text


def test_dashboard_displays_recent_activity(dashboard_client, dashboard_admin):
    client, factory = dashboard_client
    db = factory()
    db.add(
        AuditLog(
            actor_type="ADMIN",
            actor_id="1",
            action="DASHBOARD_TEST_ACTIVITY",
            entity="dashboard",
            entity_id="test",
        )
    )
    db.commit()
    db.close()
    _authenticate(client, factory, dashboard_admin)
    response = client.get("/admin")
    assert response.status_code == 200
    assert "DASHBOARD_TEST_ACTIVITY" in response.text
