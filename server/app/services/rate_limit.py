"""Login rate limiting based on the login_attempts table."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.login_attempt import LoginAttempt


def check_login_rate_limit(
    db: Session,
    ip: str,
    username: str,
    max_attempts: int,
    window_minutes: int,
) -> bool:
    """Return whether the IP and username pair is allowed to attempt login."""
    cutoff = utc_now() - timedelta(minutes=window_minutes)
    statement = select(func.count(LoginAttempt.id)).where(
        LoginAttempt.ip == ip,
        LoginAttempt.username == username,
        LoginAttempt.success.is_(False),
        LoginAttempt.created_at > cutoff,
    )
    failures = db.scalar(statement) or 0
    return failures < max_attempts


def record_login_attempt(db: Session, ip: str, username: str, success: bool) -> None:
    """Add a login attempt without committing the caller's transaction."""
    db.add(LoginAttempt(ip=ip, username=username, success=success))
