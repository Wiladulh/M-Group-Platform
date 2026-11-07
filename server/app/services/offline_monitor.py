"""Periodic server-side detection for devices that stop heartbeating."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Device, DeviceEvent
from app.services.alerts import fire_device_offline
from app.services.settings import get_setting
from app.ws.connection_manager import manager
from app.ws.heartbeat import heartbeat

logger = logging.getLogger(__name__)


async def offline_monitor_loop(app) -> None:
    while True:
        await asyncio.sleep(10)
        for device_pk in manager.connected_devices():
            if not heartbeat.is_alive(device_pk):
                ws = manager._connections.get(device_pk)
                if ws is not None:
                    try:
                        await ws.close(code=4006, reason="heartbeat_timeout")
                    except Exception:
                        pass
                with SessionLocal() as session:
                    device = session.get(Device, device_pk)
                    if device is not None:
                        fire_device_offline(device, datetime.now(UTC))
                await manager.disconnect(device_pk)
        with SessionLocal() as session:
            threshold = int(get_setting(session, "device_offline_alert_s", 120))
            cutoff = datetime.now(UTC) - timedelta(seconds=threshold)
            devices = session.scalars(select(Device).where(
                Device.status == "ACTIVE", Device.ws_connected.is_(False),
                Device.last_seen_at.is_not(None), Device.last_seen_at < cutoff,
            )).all()
            for device in devices:
                opened = session.scalar(select(DeviceEvent.id).where(
                    DeviceEvent.device_id == device.id, DeviceEvent.event == "OFFLINE",
                    DeviceEvent.duration_s.is_(None), DeviceEvent.at >= cutoff,
                ).limit(1))
                if opened is None:
                    fire_device_offline(device, device.last_seen_at)
                    session.add(DeviceEvent(device_id=device.id, event="OFFLINE",
                                            at=datetime.now(UTC), detail="alert_fired"))
            session.commit()
