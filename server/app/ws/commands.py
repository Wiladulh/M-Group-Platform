"""Acknowledged server-to-device binding command builders."""

from app.ws.connection_manager import manager
from app.ws.protocol import EnvelopeEnvelope


async def send_bind_start(
    device_id_pk: int,
    session_uuid: str,
    member_name: str,
    mode: str,
    timeout_s: int,
) -> bool:
    envelope = EnvelopeEnvelope.build(
        "bind.start",
        {
            "session_uuid": session_uuid,
            "member_name": member_name,
            "mode": mode,
            "timeout_s": timeout_s,
        },
    )
    return await manager.send_with_ack(device_id_pk, envelope)


async def send_bind_error(device_id_pk: int, session_uuid: str, code: str, message: str) -> bool:
    envelope = EnvelopeEnvelope.build(
        "bind.error",
        {"session_uuid": session_uuid, "code": code, "message": message},
    )
    return await manager.send_with_ack(device_id_pk, envelope)


async def send_bind_done(device_id_pk: int, session_uuid: str, uid: str, status: str) -> bool:
    uid_masked = "••••" + uid[-4:]
    envelope = EnvelopeEnvelope.build(
        "bind.done",
        {"session_uuid": session_uuid, "uid_masked": uid_masked, "status": status},
    )
    return await manager.send_with_ack(device_id_pk, envelope)


async def send_bind_cancel(device_id_pk: int, session_uuid: str, reason: str) -> bool:
    envelope = EnvelopeEnvelope.build(
        "bind.cancel",
        {"session_uuid": session_uuid, "reason": reason},
    )
    return await manager.send_with_ack(device_id_pk, envelope)
