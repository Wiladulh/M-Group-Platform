"""Device WebSocket authentication and message receive loop."""

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select

from app import db
from app.errors import DomainError
from app.models import CardBindSession, Device, Member
from app.security.device_token import verify_device_token
from app.services.binding import BindingService
from app.ws.commands import send_bind_cancel, send_bind_done, send_bind_error, send_bind_start
from app.ws.connection_manager import manager
from app.ws.heartbeat import heartbeat
from app.ws.protocol import EnvelopeEnvelope, HelloData

logger = logging.getLogger(__name__)
IDLE_DISCONNECT_S = 30
HELLO_TIMEOUT_S = 10


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def ws_device_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    device_pk: int | None = None
    try:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=HELLO_TIMEOUT_S)
            message = EnvelopeEnvelope.model_validate_json(raw)
            if message.type != "hello":
                await websocket.close(code=4002, reason="hello_required")
                return
            hello = HelloData.model_validate(message.data)
        except (TimeoutError, ValidationError, ValueError):
            await websocket.close(code=4002, reason="hello_required")
            return

        with db.SessionLocal() as session:
            device = session.scalar(select(Device).where(Device.device_id == hello.device_id))
            if (
                device is None
                or device.status != "ACTIVE"
                or not verify_device_token(hello.token, device.token_hash)
            ):
                await websocket.close(code=4003, reason="unauthorized")
                return
            device_pk = device.id
            device.last_seen_at = datetime.now(UTC)
            device.last_ip = websocket.client.host if websocket.client else None
            device.fw_version = hello.fw_version
            if hello.mode is not None and device.type == "cashier":
                device.reported_mode = hello.mode
            session.commit()

        await manager.connect(device_pk, websocket)
        heartbeat.record_ping(device_pk)
        await websocket.send_text(
            EnvelopeEnvelope.build(
                "hello_ok",
                {
                    "device_id": hello.device_id,
                    "server_time_utc": _utc_iso(),
                    "ping_interval_s": 10,
                    "pong_timeout_s": 25,
                    "idle_disconnect_s": 30,
                },
                message_id=message.id,
            ).model_dump_json()
        )
        with db.SessionLocal() as session:
            pending_bind = session.scalar(
                select(CardBindSession)
                .where(
                    CardBindSession.device_id == device_pk,
                    CardBindSession.state.in_(("WAITING_DEVICE", "WAITING_CARD")),
                )
                .order_by(CardBindSession.created_at.asc())
            )
            if pending_bind is not None:
                member = session.get(Member, pending_bind.member_id)
                if member is not None:
                    timeout_s = max(
                        1, int((pending_bind.expires_at - datetime.now(UTC)).total_seconds())
                    )
                    asyncio.create_task(
                        send_bind_start(
                            device_pk,
                            pending_bind.session_uuid,
                            member.full_name,
                            pending_bind.mode,
                            timeout_s,
                        )
                    )
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=IDLE_DISCONNECT_S)
            except TimeoutError:
                await websocket.close(code=4005, reason="idle")
                break
            try:
                incoming = EnvelopeEnvelope.model_validate_json(raw)
            except ValidationError:
                logger.warning("device_ws_invalid_message device_id=%s", hello.device_id)
                continue
            if incoming.type == "ping":
                heartbeat.record_ping(device_pk)
                heartbeat.record_pong(device_pk)
                with db.SessionLocal.begin() as session:
                    current = session.get(Device, device_pk)
                    if current is not None:
                        current.last_seen_at = datetime.now(UTC)
                await websocket.send_text(
                    EnvelopeEnvelope.build(
                        "pong", {"server_time_utc": _utc_iso()}, message_id=incoming.id
                    ).model_dump_json()
                )
            elif incoming.type == "pong":
                heartbeat.record_pong(device_pk)
                manager._last_pong_utc[device_pk] = datetime.now(UTC)
            elif incoming.type == "status":
                with db.SessionLocal.begin() as session:
                    current = session.get(Device, device_pk)
                    if current is not None:
                        current.last_heartbeat_json = json.dumps(
                            {"state": incoming.data.get("state"), "ts": incoming.ts}
                        )
            elif incoming.type == "ack":
                manager.record_ack(device_pk, str(incoming.data.get("id", "")))
                logger.debug(
                    "device_ws_ack device_id=%s message_id=%s",
                    hello.device_id,
                    incoming.data.get("id"),
                )
            elif incoming.type == "bind.card_scanned":
                session_uuid = str(incoming.data.get("session_uuid", ""))
                error = None
                with db.SessionLocal.begin() as session:
                    try:
                        raw_ts = incoming.data.get("ts")
                        hw_ts = (
                            datetime.fromtimestamp(raw_ts, UTC)
                            if isinstance(raw_ts, (int, float))
                            else datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                        )
                        BindingService(session).on_card_scanned(
                            session_uuid, str(incoming.data.get("uid", "")), hw_ts
                        )
                    except (DomainError, ValueError, TypeError) as exc:
                        error = exc
                if error is not None:
                    asyncio.create_task(
                        send_bind_error(
                            device_pk,
                            session_uuid,
                            getattr(error, "code", "VALIDATION_ERROR"),
                            str(error),
                        )
                    )
            elif incoming.type == "bind.pin_submitted":
                session_uuid = str(incoming.data.get("session_uuid", ""))
                error = None
                result = None
                with db.SessionLocal.begin() as session:
                    try:
                        result = BindingService(session).on_pin_submitted(
                            session_uuid,
                            str(incoming.data.get("pin", "")),
                            incoming.data.get("confirm"),
                        )
                    except DomainError as exc:
                        error = exc
                if error is not None:
                    await send_bind_error(
                        device_pk,
                        session_uuid,
                        getattr(error, "code", "VALIDATION_ERROR"),
                        str(error),
                    )
                elif result is not None and result.state == "DONE":
                    asyncio.create_task(
                        send_bind_done(
                            device_pk, session_uuid, result.uid_scanned or "", "ACTIVE"
                        )
                    )
            elif incoming.type == "bind.cancel":
                session_uuid = str(incoming.data.get("session_uuid", ""))
                reason = str(incoming.data.get("reason", "cancelled"))
                error = None
                with db.SessionLocal.begin() as session:
                    try:
                        BindingService(session).on_device_cancel(session_uuid)
                    except DomainError as exc:
                        error = exc
                if error is not None:
                    asyncio.create_task(
                        send_bind_error(
                            device_pk,
                            session_uuid,
                            getattr(error, "code", "BIND_FAILED"),
                            str(error),
                        )
                    )
                else:
                    asyncio.create_task(send_bind_cancel(device_pk, session_uuid, reason))
            elif incoming.type.startswith("bind."):
                logger.warning(
                    "unknown_bind_message device_id=%s type=%s",
                    hello.device_id,
                    incoming.type,
                )
            else:
                logger.debug(
                    "device_ws_unknown_message device_id=%s type=%s",
                    hello.device_id,
                    incoming.type,
                )
    except WebSocketDisconnect:
        pass
    finally:
        if device_pk is not None:
            await manager.disconnect(device_pk, websocket)
            heartbeat.clear(device_pk)
