"""HTTP tests for the browser administrator authentication flow."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AdminSession, AdminUser, Base, LoginAttempt
from app.models.base import utc_now
from app.security.session_token import hash_session_token
from app.services.admin_auth import create_admin_session
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
@pytest.fixture
def web_client() -> Iterator[tuple[TestClient, sessionmaker]]:
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
    with TestClient(app) as test_client:
        yield test_client, factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def admin_user(web_client):
    _, factory = web_client
    db = factory()
    user = AdminUser(
        id=1,
        username="admin",
        display_name="Administrator",
        password_hash=PasswordHasher().hash("CorrectHorseBatteryStaple!"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _csrf(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def _login(client: TestClient, username="admin", password="CorrectHorseBatteryStaple!"):
    page = client.get("/admin/login")
    return client.post(
        "/admin/login",
        data={"username": username, "password": password, "csrf_token": _csrf(page)},
        follow_redirects=False,
    )


def _authenticated_cookie(client, factory, user):
    db = factory()
    token, _session = create_admin_session(db, user, "127.0.0.1", "pytest", 1440)
    db.commit()
    db.close()
    client.cookies.set(get_settings().session_cookie_name, token)
    return token


def test_login_page_renders_csrf(web_client):
    client, _ = web_client
    response = client.get("/admin/login")
    assert response.status_code == 200
    assert 'name="csrf_token"' in response.text


def test_login_success_sets_session_cookie(web_client, admin_user):
    client, _ = web_client
    response = _login(client)
    assert response.status_code == 303
    assert get_settings().session_cookie_name in response.cookies


def test_login_wrong_password_is_rejected(web_client, admin_user):
    client, _ = web_client
    response = _login(client, password="incorrect-password")
    assert response.status_code == 401


def test_login_unknown_username_is_rejected(web_client):
    client, _ = web_client
    response = _login(client, username="unknown")
    assert response.status_code == 401


def test_login_rate_limit_blocks_sixth_failure(web_client):
    client, factory = web_client
    db = factory()
    db.add_all([
        LoginAttempt(ip="testclient", username="admin", success=False)
        for _ in range(5)
    ])
    db.commit()
    db.close()
    page = client.get("/admin/login")
    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "bad", "csrf_token": _csrf(page)},
    )
    assert response.status_code == 429


def test_login_rejects_missing_csrf(web_client):
    client, _ = web_client
    response = client.post("/admin/login", data={"username": "admin", "password": "x"})
    assert response.status_code == 400


def test_admin_route_requires_session(web_client):
    client, _ = web_client
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_rejects_authorization_header(web_client):
    client, _ = web_client
    response = client.get("/admin", headers={"Authorization": "Bearer anything"})
    assert response.status_code == 401


def test_admin_htmx_uses_hx_redirect(web_client):
    client, _ = web_client
    response = client.get("/admin", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/admin/login"


def test_session_sliding_refreshes_expiry(web_client, admin_user):
    client, factory = web_client
    token = _authenticated_cookie(client, factory, admin_user)
    db = factory()
    session = db.scalar(
        select(AdminSession).where(AdminSession.session_hash == hash_session_token(token))
    )
    naive_now = datetime.now(UTC).replace(tzinfo=None)
    session.last_seen_at = naive_now - timedelta(hours=1)
    session.expires_at = naive_now + timedelta(minutes=1)
    db.commit()
    old_expiry = session.expires_at
    db.close()
    response = client.get("/admin")
    assert response.status_code == 200
    db = factory()
    refreshed = db.scalar(select(AdminSession).where(AdminSession.id == session.id))
    assert refreshed.expires_at > old_expiry
    db.close()


def test_expired_session_redirects_to_login(web_client, admin_user):
    client, factory = web_client
    token = _authenticated_cookie(client, factory, admin_user)
    db = factory()
    session = db.scalar(
        select(AdminSession).where(AdminSession.session_hash == hash_session_token(token))
    )
    session.expires_at = utc_now() - timedelta(minutes=1)
    db.commit()
    db.close()
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303


def test_logout_revokes_current_session(web_client, admin_user):
    client, factory = web_client
    token = _authenticated_cookie(client, factory, admin_user)
    page = client.get("/admin")
    response = client.post(
        "/admin/logout",
        data={"csrf_token": _csrf(page)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db = factory()
    session = db.scalar(
        select(AdminSession).where(AdminSession.session_hash == hash_session_token(token))
    )
    assert session.revoked_at is not None
    db.close()


def test_password_change_revokes_other_sessions(web_client, admin_user):
    client, factory = web_client
    _authenticated_cookie(client, factory, admin_user)
    db = factory()
    _other_token, other = create_admin_session(db, admin_user, "192.0.2.2", "other", 1440)
    db.commit()
    other_id = other.id
    db.close()
    page = client.get("/admin/settings/password")
    response = client.post(
        "/admin/settings/password",
        data={
            "old_password": "CorrectHorseBatteryStaple!",
            "new_password": "A-New-Long-Password-2026!",
            "confirm_password": "A-New-Long-Password-2026!",
            "csrf_token": _csrf(page),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db = factory()
    assert db.get(AdminSession, other_id).revoked_at is not None
    db.close()
