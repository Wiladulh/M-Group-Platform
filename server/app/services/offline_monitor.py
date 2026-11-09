"""Periodic server-side detection for devices that stop heartbeating."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import Device, DeviceEvent
from app.services.alerts import fire_device_offline
from app.services.settings import get_setting
from app.ws.connection_manager import manager
from app.ws.heartbeat import heartbeat

logger = logging.getLogger(__name__)


def _claim_offline_alert(session, event_id: int) -> bool:
    """Atomically claim an OFFLINE event so concurrent monitors cannot alert twice."""
    result = session.execute(
        update(DeviceEvent)
        .where(
            DeviceEvent.id == event_id,
            or_(DeviceEvent.detail.is_(None), DeviceEvent.detail != "alert_fired"),
        )
        .values(detail="alert_fired")
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return result.rowcount == 1


async def offline_monitor_once(app) -> None:
    for device_pk in manager.connected_devices():
        if not heartbeat.is_alive(device_pk):
            ws = manager._connections.get(device_pk)
            if ws is not None:
                with suppress(Exception):
                    await ws.close(code=4006, reason="heartbeat_timeout")
            with db.SessionLocal() as session:
                device = session.get(Device, device_pk)
                if device is not None:
                    fire_device_offline(device, datetime.now(UTC))
            await manager.disconnect(device_pk, ws)
            heartbeat.clear(device_pk)

    with db.SessionLocal() as session:
        try:
            threshold = int(get_setting(session, "device_offline_alert_s", 120))
            cutoff = datetime.now(UTC) - timedelta(seconds=threshold)
            devices = session.scalars(
                select(Device).where(
                    Device.status == "ACTIVE",
                    Device.ws_connected.is_(False),
                    Device.last_seen_at.is_not(None),
                    Device.last_seen_at < cutoff,
                )
            ).all()
            for device in devices:
                opened = session.scalar(
                    select(DeviceEvent)
                    .where(
                        DeviceEvent.device_id == device.id,
                        DeviceEvent.event == "OFFLINE",
                        DeviceEvent.duration_s.is_(None),
                    )
                    .order_by(DeviceEvent.at.desc())
                    .limit(1)
                )
                if opened is not None and _claim_offline_alert(session, opened.id):
                    fire_device_offline(device, device.last_seen_at)
        except SQLAlchemyError:
            logger.debug("offline_monitor_database_not_ready", exc_info=True)
            session.rollback()


async def offline_monitor_loop(app) -> None:
    while True:
        await asyncio.sleep(10)
        await offline_monitor_once(app)
