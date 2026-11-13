"""Tests for login rate limiting helpers."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base, utc_now
from app.models.login_attempt import LoginAttempt
from app.services.rate_limit import check_login_rate_limit, record_login_attempt


@pytest.fixture
def db_session(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'rate-limit-test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _record_failures(db_session: Session, count: int) -> None:
    db_session.add_all(
        [
            LoginAttempt(
                ip="192.0.2.10",
                username="admin",
                success=False,
            )
            for _ in range(count)
        ]
    )
    db_session.flush()


def test_no_attempts_allowed(db_session: Session) -> None:
    assert check_login_rate_limit(db_session, "192.0.2.10", "admin", 5, 15) is True


def test_below_limit_allowed(db_session: Session) -> None:
    _record_failures(db_session, 4)

    assert check_login_rate_limit(db_session, "192.0.2.10", "admin", 5, 15) is True


def test_at_limit_blocked(db_session: Session) -> None:
    _record_failures(db_session, 5)

    assert check_login_rate_limit(db_session, "192.0.2.10", "admin", 5, 15) is False


def test_success_does_not_reset_counter(db_session: Session) -> None:
    _record_failures(db_session, 4)
    record_login_attempt(db_session, "192.0.2.10", "admin", True)
    record_login_attempt(db_session, "192.0.2.10", "admin", False)
    db_session.flush()

    assert check_login_rate_limit(db_session, "192.0.2.10", "admin", 5, 15) is False


def test_old_attempts_outside_window_not_counted(db_session: Session) -> None:
    db_session.add(
        LoginAttempt(
            ip="192.0.2.10",
            username="admin",
            success=False,
            created_at=utc_now() - timedelta(minutes=16),
        )
    )
    db_session.flush()

    assert check_login_rate_limit(db_session, "192.0.2.10", "admin", 5, 15) is True


def test_record_attempt_creates_row(db_session: Session) -> None:
    record_login_attempt(db_session, "192.0.2.10", "admin", False)
    db_session.flush()

    row = db_session.query(LoginAttempt).one()
    assert row.ip == "192.0.2.10"
    assert row.username == "admin"
    assert row.success is False
