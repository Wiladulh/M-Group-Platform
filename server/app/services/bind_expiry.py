"""Expire abandoned remote card binding sessions and notify their devices."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import CardBindSession
from app.services.binding import ACTIVE_STATES, BindingService
from app.ws.commands import send_bind_cancel

logger = logging.getLogger(__name__)


async def bind_expiry_once(app=None) -> int:
    expired: list[tuple[int, str]] = []
    try:
        with db.SessionLocal.begin() as session:
            rows = session.scalars(
                select(CardBindSession).where(
                    CardBindSession.state.in_(ACTIVE_STATES),
                    CardBindSession.expires_at < datetime.now(UTC),
                )
            ).all()
            service = BindingService(session)
            for row in rows:
                service.expire_session(row.session_uuid)
                expired.append((row.device_id, row.session_uuid))
    except SQLAlchemyError:
        logger.debug("bind_expiry_database_not_ready", exc_info=True)
        return 0
    for device_id, session_uuid in expired:
        await send_bind_cancel(device_id, session_uuid, "expired")
    return len(expired)


async def bind_expiry_loop(app) -> None:
    while True:
        await asyncio.sleep(5)
        await bind_expiry_once(app)
