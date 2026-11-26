"""HTTP tests for member detail, profile edit, status change, and NIK reveal."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AdminUser, AuditLog, Base, Card, Member, Transaction
from app.security.encryption import blind_index_nik, encrypt_nik
from app.services.admin_auth import create_admin_session
from app.services.cache_version import get_member_cache_version
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NIK_A = "3201123456781234"
NIK_B = "3201999988887777"


@pytest.fixture
def detail_client() -> Iterator[tuple[TestClient, sessionmaker]]:
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


def _make_admin(factory) -> AdminUser:
    db = factory()
    user = AdminUser(
        id=1,
        username="detail-admin",
        display_name="Detail Admin",
        password_hash=PasswordHasher().hash("CorrectHorseBatteryStaple!"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _login(client: TestClient, factory, user: AdminUser) -> None:
    db = factory()
    token, _session = create_admin_session(db, user, "127.0.0.1", "pytest", 1440)
    db.commit()
    db.close()
    client.cookies.set(get_settings().session_cookie_name, token)


def _csrf(client: TestClient) -> str:
    """Fetch a page that carries a fresh CSRF token and extract it."""
    html = client.get("/admin/members/new").text
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _seed_member(factory, nik: str = NIK_A, name: str = "Budi Santoso") -> int:
    db = factory()
    member = Member(
        member_code="MG-A00001",
        full_name=name,
        nik_enc=encrypt_nik(nik),
        nik_idx=blind_index_nik(nik),
        phone="081234567890",
        balance=15000,
        notes="catatan awal",
    )
    db.add(member)
    db.flush()
    db.add(
        Card(
            member_id=member.id,
            uid="04A1B2C3",
            pin_hash="x",
            status="ACTIVE",
            bound_at=datetime(2026, 11, 1, 3, 0, tzinfo=UTC),
        )
    )
    db.add(
        Transaction(
            txn_uuid="11111111-1111-1111-1111-111111111111",
            member_id=member.id,
            type="TOPUP",
            amount=15000,
            direction="CREDIT",
            balance_before=0,
            balance_after=15000,
            status="COMPLETED",
            source="ADMIN",
            occurred_at=datetime(2026, 11, 2, 4, 0, tzinfo=UTC),
            performed_by_type="ADMIN",
            performed_by_id="1",
        )
    )
    db.commit()
    member_id = member.id
    db.close()
    return member_id


def _audit_actions(factory) -> list[str]:
    db = factory()
    rows = db.scalars(select(AuditLog.action)).all()
    db.close()
    return list(rows)


def test_detail_requires_login(detail_client):
    client, factory = detail_client
    member_id = _seed_member(factory)
    response = client.get(f"/admin/members/{member_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_detail_unknown_member_is_404(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    assert client.get("/admin/members/9999").status_code == 404


def test_detail_shows_identity_card_finance_and_hides_nik(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    member_id = _seed_member(factory)
    response = client.get(f"/admin/members/{member_id}")
    assert response.status_code == 200
    assert "Budi Santoso" in response.text
    assert "MG-A00001" in response.text
    assert NIK_A not in response.text
    assert "••••B2C3" in response.text
    assert "Rp 15.000" in response.text
    assert "TOPUP" in response.text


def test_reveal_nik_shows_value_and_audits(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    member_id = _seed_member(factory)
    token = _csrf(client)
    response = client.post(f"/admin/members/{member_id}/reveal-nik", data={"csrf_token": token})
    assert response.status_code == 200
    assert NIK_A in response.text
    assert "MEMBER_NIK_REVEALED" in _audit_actions(factory)


def test_edit_form_does_not_prefill_nik(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    member_id = _seed_member(factory)
    response = client.get(f"/admin/members/{member_id}/edit")
    assert response.status_code == 200
    assert NIK_A not in response.text
    assert 'name="nik" value=""' in response.text


def test_edit_updates_profile_without_changing_nik(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    member_id = _seed_member(factory)
    token = _csrf(client)
    response = client.post(
        f"/admin/members/{member_id}/edit",
        data={
            "csrf_token": token,
            "full_name": "Budi Santoso Putra",
            "nik": "",
            "phone": "+6281298765432",
            "notes": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db = factory()
    member = db.get(Member, member_id)
    assert member.full_name == "Budi Santoso Putra"
    assert member.phone == "081298765432"
    assert member.nik_idx == blind_index_nik(NIK_A)
    db.close()
    assert "MEMBER_UPDATED" in _audit_actions(factory)


def test_edit_nik_reindexes_and_audit_hides_value(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    member_id = _seed_member(factory)
    token = _csrf(client)
    response = client.post(
        f"/admin/members/{member_id}/edit",
        data={
            "csrf_token": token,
            "full_name": "Budi Santoso",
            "nik": NIK_B,
            "phone": "081234567890",
            "notes": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db = factory()
    member = db.get(Member, member_id)
    assert member.nik_idx == blind_index_nik(NIK_B)
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "MEMBER_UPDATED")).one()
    db.close()
    assert "NIK diubah" in audit.after_json
    assert NIK_B not in audit.after_json
    assert NIK_A not in audit.after_json


def test_edit_duplicate_nik_is_rejected(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    _seed_member(factory, nik=NIK_A, name="Member Satu")
    db = factory()
    other = Member(
        member_code="MG-A00002",
        full_name="Member Dua",
        nik_enc=encrypt_nik(NIK_B),
        nik_idx=blind_index_nik(NIK_B),
        phone="081200000000",
        balance=0,
    )
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()
    token = _csrf(client)
    response = client.post(
        f"/admin/members/{other_id}/edit",
        data={
            "csrf_token": token,
            "full_name": "Member Dua",
            "nik": NIK_A,
            "phone": "081200000000",
            "notes": "",
        },
    )
    assert response.status_code == 409
    assert "NIK sudah terdaftar" in response.text


def test_edit_invalid_phone_returns_422(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    member_id = _seed_member(factory)
    token = _csrf(client)
    response = client.post(
        f"/admin/members/{member_id}/edit",
        data={
            "csrf_token": token,
            "full_name": "Budi Santoso",
            "nik": "",
            "phone": "12345",
            "notes": "",
        },
    )
    assert response.status_code == 422


def test_edit_rejects_bad_csrf(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    member_id = _seed_member(factory)
    response = client.post(
        f"/admin/members/{member_id}/edit",
        data={
            "csrf_token": "salah",
            "full_name": "Budi Santoso",
            "nik": "",
            "phone": "081234567890",
            "notes": "",
        },
    )
    assert response.status_code == 403


def test_suspend_requires_reason_and_bumps_cache(detail_client):
    client, factory = detail_client
    _login(client, factory, _make_admin(factory))
    member_id = _seed_member(factory)
    token = _csrf(client)

    version_before = _cache_version(factory)
    no_reason = client.post(
        f"/admin/members/{member_id}/status",
        data={"csrf_token": token, "status": "SUSPENDED", "reason": ""},
        follow_redirects=False,
    )
    assert no_reason.status_code == 303
    assert "Alasan" in no_reason.headers["location"]
    db = factory()
    assert db.get(Member, member_id).status == "ACTIVE"
    db.close()

    response = client.post(
        f"/admin/members/{member_id}/status",
        data={
            "csrf_token": token,
            "status": "SUSPENDED",
            "reason": "Kartu dipinjamkan",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db = factory()
    assert db.get(Member, member_id).status == "SUSPENDED"
    db.close()
    assert _cache_version(factory) > version_before
    assert "MEMBER_STATUS_CHANGED" in _audit_actions(factory)


def _cache_version(factory) -> int:
    db = factory()
    value = get_member_cache_version(db)
    db.close()
    return value
