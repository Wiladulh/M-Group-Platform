"""Tests for the login_attempts ORM model and lookup index."""

import pytest
from app.models import Base, LoginAttempt
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'login-attempts.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_login_attempts_table_and_index_exist(db_session) -> None:
    """The login_attempts table and composite lookup index are present."""
    inspector = inspect(db_session.get_bind())
    assert "login_attempts" in inspector.get_table_names()
    index_names = {index["name"] for index in inspector.get_indexes("login_attempts")}
    assert "ix_login_attempts_lookup" in index_names


def test_login_attempt_insert_populates_timestamps(db_session) -> None:
    """Inserting an attempt fills id, created_at, and updated_at."""
    attempt = LoginAttempt(ip="127.0.0.1", username="admin", success=False)
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    assert attempt.id is not None
    assert attempt.created_at is not None
    assert attempt.updated_at is not None


def test_login_attempt_filter_by_ip_username_success(db_session) -> None:
    """Failed attempts are filterable by ip, username, and success."""
    db_session.add_all(
        [
            LoginAttempt(ip="127.0.0.1", username="admin", success=False),
            LoginAttempt(ip="127.0.0.1", username="admin", success=False),
            LoginAttempt(ip="127.0.0.1", username="admin", success=True),
            LoginAttempt(ip="127.0.0.2", username="admin", success=False),
        ]
    )
    db_session.commit()

    failures = db_session.scalars(
        select(LoginAttempt).where(
            LoginAttempt.ip == "127.0.0.1",
            LoginAttempt.username == "admin",
            LoginAttempt.success.is_(False),
        )
    ).all()
    assert len(failures) == 2
