"""Monotonic version for device member-cache snapshots."""

from sqlalchemy.orm import Session

from app.services.settings import get_setting, set_setting


def get_member_cache_version(session: Session) -> int:
    return int(get_setting(session, "member_cache_version", 0))


def bump_member_cache_version(session: Session) -> int:
    version = get_member_cache_version(session) + 1
    set_setting(session, "member_cache_version", version)
    return version
