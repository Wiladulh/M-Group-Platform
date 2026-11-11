"""Admin session lifecycle helpers (create, lookup, touch, revoke)."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import AdminSession, AdminUser
from app.models.base import utc_now
from app.security.session_token import generate_session_token, hash_session_token


def create_admin_session(
    db: Session,
    user: AdminUser,
    ip: str | None,
    user_agent: str | None,
    idle_minutes: int,
) -> tuple[str, AdminSession]:
    """Create a server-side session and return its plaintext token and row."""
    token = generate_session_token()
    session = AdminSession(
        user_id=user.id,
        session_hash=hash_session_token(token),
        last_seen_at=utc_now(),
        expires_at=utc_now() + timedelta(minutes=idle_minutes),
        ip=ip,
        user_agent=user_agent,
    )
    db.add(session)
    db.flush()
    return token, session


def lookup_admin_session(db: Session, token: str) -> AdminSession | None:
    """Return an active, unexpired session matching the supplied token."""
    statement = select(AdminSession).where(
        AdminSession.session_hash == hash_session_token(token),
        AdminSession.revoked_at.is_(None),
        AdminSession.expires_at > utc_now(),
    )
    return db.scalar(statement)


def touch_admin_session(db: Session, session: AdminSession, idle_minutes: int) -> None:
    """Refresh the session's activity timestamp and sliding idle expiry."""
    now = utc_now()
    session.last_seen_at = now
    session.expires_at = now + timedelta(minutes=idle_minutes)
    db.add(session)


def revoke_admin_session(db: Session, session: AdminSession) -> None:
    """Mark a session as revoked."""
    session.revoked_at = utc_now()
    db.add(session)


def revoke_other_sessions(
    db: Session, user: AdminUser, keep_session: AdminSession
) -> int:
    """Revoke every unrevoked session for the user except the supplied session."""
    sessions = db.scalars(
        select(AdminSession).where(
            AdminSession.user_id == user.id,
            AdminSession.id != keep_session.id,
            AdminSession.revoked_at.is_(None),
        )
    ).all()
    now = utc_now()
    for session in sessions:
        session.revoked_at = now
    return len(sessions)
