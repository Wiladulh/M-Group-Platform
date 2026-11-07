"""Single active WebSocket connection per registered device."""

import asyncio
import logging
import os
from contextlib import suppress
from datetime import UTC

from fastapi import WebSocket
from sqlalchemy import select

from app import db
from app.models import Device, DeviceEvent
from app.models.base import utc_now
from app.services.alerts import fire_device_online
from app.services.settings import get_setting
from app.ws.protocol import EnvelopeEnvelope

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}
        self._last_pong_utc = {}
        self._connected_since = {}
        self._pending_acks: dict[int, dict[str, asyncio.Task]] = {}

    async def connect(self, device_id_pk: int, ws: WebSocket) -> None:
        old = self._connections.get(device_id_pk)
        if old is not None and old is not ws:
            with suppress(Exception):
                await old.close(code=4001, reason="replaced")
        now = utc_now()
        self._connections[device_id_pk] = ws
        self._connected_since[device_id_pk] = now
        with db.SessionLocal.begin() as session:
            device = session.get(Device, device_id_pk)
            if device is None:
                return
            previous = session.scalar(
                select(DeviceEvent)
                .where(
                    DeviceEvent.device_id == device_id_pk,
                    DeviceEvent.event == "OFFLINE",
                    DeviceEvent.duration_s.is_(None),
                )
                .order_by(DeviceEvent.at.desc())
                .limit(1)
            )
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
            if event_name == "ONLINE":
                fire_device_online(device)

    async def disconnect(self, device_id_pk: int, ws: WebSocket | None = None) -> None:
        current = self._connections.get(device_id_pk)
        if ws is not None and current is not ws:
            return
        self._connections.pop(device_id_pk, None)
        self._last_pong_utc.pop(device_id_pk, None)
        since = self._connected_since.pop(device_id_pk, None)
        for task in self._pending_acks.pop(device_id_pk, {}).values():
            task.cancel()
        now = utc_now()
        with db.SessionLocal.begin() as session:
            device = session.get(Device, device_id_pk)
            if device is None:
                return
            device.ws_connected = False
            session.add(
                DeviceEvent(
                    device_id=device_id_pk,
                    event="OFFLINE",
                    at=now,
                    duration_s=None,
                    detail=str(max(0, int((now - since).total_seconds()))) if since else None,
                )
            )

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

    async def send_with_ack(self, device_id_pk: int, envelope: EnvelopeEnvelope) -> bool:
        timeout_s = float(os.getenv("BIND_ACK_TIMEOUT_S", "5"))
        pending = self._pending_acks.setdefault(device_id_pk, {})
        task = asyncio.create_task(self._ack_timeout(device_id_pk, envelope.id, timeout_s))
        pending[envelope.id] = task
        sent = await self.send(device_id_pk, envelope)
        if not sent:
            pending.pop(envelope.id, None)
            task.cancel()
        return sent

    async def _ack_timeout(self, device_id_pk: int, message_id: str, timeout_s: float) -> None:
        await asyncio.sleep(timeout_s)
        pending = self._pending_acks.get(device_id_pk, {})
        if pending.pop(message_id, None) is not None:
            logger.warning(
                "device_ws_ack_timeout device_pk=%s message_id=%s",
                device_id_pk,
                message_id,
            )

    def record_ack(self, device_id_pk: int, message_id: str) -> bool:
        task = self._pending_acks.get(device_id_pk, {}).pop(message_id, None)
        if task is None:
            return False
        task.cancel()
        return True

    async def is_connected(self, device_id_pk: int) -> bool:
        return device_id_pk in self._connections

    def connected_count(self) -> int:
        return len(self._connections)

    def connected_devices(self) -> tuple[int, ...]:
        return tuple(self._connections)


manager = ConnectionManager()
