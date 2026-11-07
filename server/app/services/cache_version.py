"""Monotonic version for device member-cache snapshots."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OfflineAllowance
from app.services.settings import get_setting, set_setting


def get_member_cache_version(session: Session) -> int:
    return int(get_setting(session, "member_cache_version", 0))


def get_member_cache_entry_version(session: Session, member_id: int, device_id: int) -> int:
    key = f"member_cache_entry_version:{device_id}:{member_id}"
    return int(get_setting(session, key, 0))


def bump_member_cache_version(session: Session, member_id: int | None = None) -> int:
    """Bump the global token and stamp that member's cached device entries."""
    version = get_member_cache_version(session) + 1
    set_setting(session, "member_cache_version", version)
    if member_id is not None:
        rows = session.scalars(
            select(OfflineAllowance).where(OfflineAllowance.member_id == member_id)
        ).all()
        for row in rows:
            key = f"member_cache_entry_version:{row.device_id}:{member_id}"
            set_setting(session, key, version)
    return version
