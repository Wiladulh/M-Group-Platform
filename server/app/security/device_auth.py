"""FastAPI dependency for bearer-authenticated registered devices."""

from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import BackgroundTasks, Depends, Header, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import db
from app.errors import DomainError
from app.models import Device
from app.security.device_token import verify_device_token


class DeviceAuthError(DomainError):
    """A generic authentication failure that does not reveal device state."""

    code = "DEVICE_REVOKED"
    status_code = 401


@dataclass(frozen=True, slots=True)
class DeviceAuthInfo:
    """Immutable device attributes needed by authenticated request handlers."""

    id: int
    device_id: str
    name: str
    type: str
    config_json: str | None
    slot_count: int | None
    reported_mode: str | None


def get_auth_session() -> Generator[Session, None, None]:
    """Yield a read-only authentication session and always close it."""
    session = db.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _update_presence(device_id: int, ip: str | None) -> None:
    """Persist a successful-auth heartbeat using an independent session."""
    session = db.SessionLocal()
    try:
        session.execute(
            update(Device)
            .where(Device.id == device_id)
            .values(last_seen_at=datetime.now(UTC), last_ip=ip)
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_device(
    request: Request,
    background: BackgroundTasks,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
    auth_session: Session = Depends(get_auth_session),  # noqa: B008
) -> DeviceAuthInfo:
    """Authenticate with an isolated session and schedule a separate heartbeat."""
    if not authorization or not x_device_id:
        raise DeviceAuthError("Unauthorized device")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise DeviceAuthError("Unauthorized device")

    device = auth_session.scalar(select(Device).where(Device.device_id == x_device_id))
    if (
        device is None
        or device.status != "ACTIVE"
        or not verify_device_token(token.strip(), device.token_hash)
    ):
        raise DeviceAuthError("Unauthorized device")

    auth_info = DeviceAuthInfo(
        id=device.id,
        device_id=device.device_id,
        name=device.name,
        type=device.type,
        config_json=device.config_json,
        slot_count=device.slot_count,
        reported_mode=device.reported_mode,
    )
    ip = request.client.host if request.client else None
    background.add_task(_update_presence, device.id, ip)
    return auth_info
