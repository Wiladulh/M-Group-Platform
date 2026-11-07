"""Single active WebSocket connection per registered device."""

import logging
from datetime import UTC

from fastapi import WebSocket
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Device, DeviceEvent
from app.models.base import utc_now
from app.services.settings import get_setting
from app.ws.protocol import EnvelopeEnvelope

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}
        self._last_pong_utc = {}
        self._connected_since = {}

    async def connect(self, device_id_pk: int, ws: WebSocket) -> None:
        old = self._connections.get(device_id_pk)
        if old is not None and old is not ws:
            try:
                await old.close(code=4001, reason="replaced")
            except Exception:
                logger.debug("old_device_socket_close_failed device_pk=%s", device_id_pk)
        now = utc_now()
        self._connections[device_id_pk] = ws
        self._connected_since[device_id_pk] = now
        with SessionLocal.begin() as session:
            device = session.get(Device, device_id_pk)
            if device is None:
                return
            previous = session.scalar(select(DeviceEvent).where(
                DeviceEvent.device_id == device_id_pk, DeviceEvent.event == "OFFLINE",
                DeviceEvent.duration_s.is_(None),
            ).order_by(DeviceEvent.at.desc()).limit(1))
            event_name = "ONLINE"
            if previous is not None:
                duration = max(0, int((now - previous.at.replace(tzinfo=UTC)).total_seconds()))
                previous.duration_s = duration
                try:
                    threshold = int(get_setting(session, "device_offline_alert_s", 120))
                except (TypeError, ValueError):
                    threshold = 120
                event_name = "ONLINE" if duration > threshold else "WIFI_RECONNECT"
            device.ws_connected = True
            session.add(DeviceEvent(device_id=device_id_pk, event=event_name, at=now))

    async def disconnect(self, device_id_pk: int, ws: WebSocket | None = None) -> None:
        current = self._connections.get(device_id_pk)
        if ws is not None and current is not ws:
            return
        self._connections.pop(device_id_pk, None)
        self._last_pong_utc.pop(device_id_pk, None)
        since = self._connected_since.pop(device_id_pk, None)
        now = utc_now()
        with SessionLocal.begin() as session:
            device = session.get(Device, device_id_pk)
            if device is None:
                return
            device.ws_connected = False
            session.add(DeviceEvent(device_id=device_id_pk, event="OFFLINE", at=now,
                                    duration_s=None,
                                    detail=str(max(0, int((now - since).total_seconds())))
                                    if since else None))

    async def send(self, device_id_pk: int, envelope: EnvelopeEnvelope) -> bool:
        ws = self._connections.get(device_id_pk)
        if ws is None:
            return False
        try:
            await ws.send_text(envelope.model_dump_json())
            return True
        except Exception:
            logger.warning("device_ws_send_failed device_pk=%s", device_id_pk)
            return False

    async def is_connected(self, device_id_pk: int) -> bool:
        return device_id_pk in self._connections

    def connected_count(self) -> int:
        return len(self._connections)

    def connected_devices(self) -> tuple[int, ...]:
        return tuple(self._connections)


manager = ConnectionManager()
