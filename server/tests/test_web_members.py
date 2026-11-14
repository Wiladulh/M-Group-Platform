"""HTTP tests for administrator member list and registration pages."""

from collections.abc import Iterator

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AdminUser, Base
from app.services.admin_auth import create_admin_session


@pytest.fixture
def members_client() -> Iterator[tuple[TestClient, sessionmaker]]:
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
def members_admin(members_client):
    _, factory = members_client
    db = factory()
    user = AdminUser(
        id=1,
        username="members-admin",
        display_name="Members Admin",
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


def test_members_list_requires_login(members_client):
    client, _ = members_client
    response = client.get("/admin/members", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_members_list_ok(members_client, members_admin):
    client, factory = members_client
    _authenticate(client, factory, members_admin)
    response = client.get("/admin/members")
    assert response.status_code == 200
    assert "Daftar Member" in response.text


def test_members_form_ok(members_client, members_admin):
    client, factory = members_client
    _authenticate(client, factory, members_admin)
    response = client.get("/admin/members/new")
    assert response.status_code == 200
    assert "csrf_token" in response.text
