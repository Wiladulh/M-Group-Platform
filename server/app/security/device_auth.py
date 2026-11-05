"""FastAPI dependency for bearer-authenticated registered devices."""

from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Device
from app.security.device_token import verify_device_token


class DeviceAuthError(Exception):
    """A domain authentication error suitable for the uniform API envelope."""

    code = "DEVICE_REVOKED"
    message = "Unauthorized device"


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "DEVICE_REVOKED", "message": "Unauthorized device", "details": {}},
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_device(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
    session: Session = Depends(get_session),
) -> Device:
    """Authenticate a device and update its successful-request heartbeat.

    last_seen_at/last_ip are intentionally updated only after every credential
    and device-status check succeeds; failed attempts never refresh presence.
    """
    if not authorization and not x_device_id:
        raise _unauthorized()
    if not authorization or not x_device_id:
        raise _unauthorized()
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()

    device = session.scalar(select(Device).where(Device.device_id == x_device_id))
    if (
        device is None
        or device.status != "ACTIVE"
        or not verify_device_token(token.strip(), device.token_hash)
    ):
        raise _unauthorized()

    device.last_seen_at = datetime.now(UTC)
    device.last_ip = request.client.host if request.client else None
    session.flush()
    return device
