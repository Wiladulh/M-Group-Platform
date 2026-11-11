"""Tests for admin audit log helper."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.audit import AuditLog
from app.models.base import Base
from app.services.audit import log_admin_action


@pytest.fixture
def db_session(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'audit-test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_log_action_creates_row(db_session: Session) -> None:
    row = log_admin_action(
        db_session,
        actor_id="1",
        action="UPDATE",
        entity="setting",
        entity_id="site_name",
        ip="192.0.2.10",
    )

    db_session.flush()

    assert row.id is not None
    assert row.actor_type == "ADMIN"
    assert row.actor_id == "1"
    assert row.action == "UPDATE"
    assert row.entity == "setting"
    assert row.entity_id == "site_name"
    assert row.ip == "192.0.2.10"


def test_before_after_serialized_as_json(db_session: Session) -> None:
    moment = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    before = {"enabled": False, "updated_at": moment}
    after = {"enabled": True, "updated_at": moment}

    row = log_admin_action(
        db_session,
        actor_id="1",
        action="UPDATE",
        entity="setting",
        before=before,
        after=after,
    )

    assert json.loads(row.before_json) == {
        "enabled": False,
        "updated_at": moment.isoformat(),
    }
    assert json.loads(row.after_json) == {
        "enabled": True,
        "updated_at": moment.isoformat(),
    }


def test_none_before_after_stored_as_null(db_session: Session) -> None:
    row = log_admin_action(
        db_session,
        actor_id="1",
        action="CREATE",
        entity="device",
        before=None,
        after=None,
    )

    assert row.before_json is None
    assert row.after_json is None


def test_actor_type_always_admin(db_session: Session) -> None:
    row = log_admin_action(
        db_session,
        actor_id="1",
        action="DELETE",
        entity="device",
    )

    assert row.actor_type == "ADMIN"
