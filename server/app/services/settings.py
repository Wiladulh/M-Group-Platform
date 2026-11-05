"""Typed access to the global key-value settings table."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Setting


def _decode(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _cast(value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(value)
    if isinstance(default, float):
        return float(value)
    if isinstance(default, str):
        return str(value)
    return value


def get_setting(session: Session, key: str, default: Any) -> Any:
    """Read one setting, casting the stored value to the default's type."""
    stored = session.scalar(select(Setting.value).where(Setting.key == key))
    return default if stored is None else _cast(_decode(stored), default)


def get_all_settings(session: Session) -> dict[str, Any]:
    """Return all settings, decoding JSON-compatible scalar values."""
    rows = session.scalars(select(Setting).order_by(Setting.key)).all()
    return {row.key: _decode(row.value) for row in rows}


def set_setting(session: Session, key: str, value: Any) -> None:
    """Insert or update a setting; caller owns the surrounding transaction."""
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    row = session.scalar(select(Setting).where(Setting.key == key))
    if row is None:
        session.add(Setting(key=key, value=encoded))
    else:
        row.value = encoded
    session.flush()
