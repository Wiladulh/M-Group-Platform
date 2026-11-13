"""Tests for admin session lifecycle helpers."""

from collections.abc import Iterator
from datetime import UTC, timedelta
from pathlib import Path

import pytest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.admin import AdminSession, AdminUser
from app.models.base import Base, utc_now
from app.security.session_token import hash_session_token
from app.services.admin_auth import (
    create_admin_session,
    lookup_admin_session,
    revoke_admin_session,
    revoke_other_sessions,
    touch_admin_session,
)



@pytest.fixture
def db_session(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'admin-auth-test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _admin_user(db_session: Session) -> AdminUser:
    user = AdminUser(
        id=1,
        username="admin",
        display_name="Administrator",
        password_hash="test-hash",
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_create_session_returns_token_and_row(db_session: Session) -> None:
    user = _admin_user(db_session)
    token, session = create_admin_session(db_session, user, "127.0.0.1", "pytest", 30)

    assert token
    assert session.user_id == user.id
    assert session.session_hash == hash_session_token(token)
    assert session.ip == "127.0.0.1"
    assert session.user_agent == "pytest"
    assert session.expires_at > session.last_seen_at


def test_lookup_valid_session(db_session: Session) -> None:
    user = _admin_user(db_session)
    token, created = create_admin_session(db_session, user, None, None, 30)

    found = lookup_admin_session(db_session, token)

    assert found is not None
    assert found.id == created.id


def test_lookup_expired_session(db_session: Session) -> None:
    user = _admin_user(db_session)
    token, session = create_admin_session(db_session, user, None, None, 30)
    session.expires_at = utc_now() - timedelta(minutes=1)
    db_session.flush()

    assert lookup_admin_session(db_session, token) is None


def test_lookup_revoked_session(db_session: Session) -> None:
    user = _admin_user(db_session)
    token, session = create_admin_session(db_session, user, None, None, 30)
    revoke_admin_session(db_session, session)
    db_session.flush()

    assert lookup_admin_session(db_session, token) is None


def test_lookup_unknown_token(db_session: Session) -> None:
    assert lookup_admin_session(db_session, "unknown-token") is None


def test_touch_updates_last_seen_and_expires(db_session: Session) -> None:
    user = _admin_user(db_session)
    _, session = create_admin_session(db_session, user, None, None, 30)
    old_last_seen = utc_now() - timedelta(hours=2)
    old_expires = utc_now() - timedelta(hours=1)
    session.last_seen_at = old_last_seen
    session.expires_at = old_expires
    db_session.flush()

    touch_admin_session(db_session, session, 45)
    db_session.flush()
    db_session.refresh(session)

    last_seen = session.last_seen_at.replace(tzinfo=UTC)
    expires = session.expires_at.replace(tzinfo=UTC)
    assert last_seen > old_last_seen
    assert expires > old_expires
    assert expires - last_seen == timedelta(minutes=45)


def test_revoke_sets_revoked_at(db_session: Session) -> None:
    user = _admin_user(db_session)
    _, session = create_admin_session(db_session, user, None, None, 30)

    revoke_admin_session(db_session, session)

    assert session.revoked_at is not None


def test_revoke_other_sessions_keeps_current(db_session: Session) -> None:
    user = _admin_user(db_session)
    _, keep = create_admin_session(db_session, user, None, None, 30)
    _, other_one = create_admin_session(db_session, user, None, None, 30)
    _, other_two = create_admin_session(db_session, user, None, None, 30)

    count = revoke_other_sessions(db_session, user, keep)

    assert count == 2
    assert keep.revoked_at is None
    assert other_one.revoked_at is not None
    assert other_two.revoked_at is not None


def test_session_hash_unique_constraint(db_session: Session) -> None:
    user = _admin_user(db_session)
    first = AdminSession(
        user_id=user.id,
        session_hash="a" * 64,
        expires_at=utc_now() + timedelta(minutes=30),
    )
    second = AdminSession(
        user_id=user.id,
        session_hash="a" * 64,
        expires_at=utc_now() + timedelta(minutes=30),
    )
    db_session.add_all([first, second])

    with pytest.raises(IntegrityError):
        db_session.flush()
