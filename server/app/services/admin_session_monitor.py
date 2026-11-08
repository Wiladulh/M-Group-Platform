"""Periodic revocation of expired administrator sessions."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import update

from app import db
from app.models import AdminSession

logger = logging.getLogger(__name__)
ADMIN_SESSION_MONITOR_INTERVAL_S = 60


async def admin_session_monitor_once() -> int:
    """Revoke all expired, not-yet-revoked admin sessions and return row count."""
    now = datetime.now(UTC)
    with db.SessionLocal.begin() as session:
        result = session.execute(
            update(AdminSession)
            .where(
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at < now,
            )
            .values(revoked_at=now)
        )
        revoked = result.rowcount or 0
    if revoked:
        logger.info("admin_session_expiry_revoked count=%s", revoked)
    return revoked


async def admin_session_monitor_loop(application) -> None:
    """Run expired admin-session revocation until application shutdown."""
    while True:
        try:
            await admin_session_monitor_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("admin_session_monitor_cycle_failed")
        finally:
            task = asyncio.current_task()
            if task is not None and not task.cancelling():
                await asyncio.sleep(ADMIN_SESSION_MONITOR_INTERVAL_S)
