"""Device-authenticated configuration endpoints."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CatalogMeta, Device
from app.schemas.device import DeviceConfigResponse
from app.security.device_auth import require_device
from app.services.settings import get_setting

router = APIRouter(
    prefix="/api/v1/device",
    tags=["device"],
    dependencies=[Depends(require_device)],
)

DEFAULTS = {
    "offline_txn_max": 30_000,
    "offline_card_cap": 50_000,
    "offline_hold_mode": "soft",
}


@router.get("/config", response_model=DeviceConfigResponse)
def get_device_config(
    device: Device = Depends(require_device),
    session: Session = Depends(get_session),
) -> DeviceConfigResponse:
    """Return effective global configuration merged with device overrides."""
    try:
        overrides = json.loads(device.config_json or "{}")
    except (TypeError, json.JSONDecodeError):
        overrides = {}
    if not isinstance(overrides, dict):
        overrides = {}

    effective = {
        "offline_txn_max": get_setting(session, "offline_txn_max", DEFAULTS["offline_txn_max"]),
        "offline_card_cap": get_setting(session, "offline_card_cap", DEFAULTS["offline_card_cap"]),
        "offline_hold_mode": get_setting(
            session, "offline_hold_mode", DEFAULTS["offline_hold_mode"]
        ),
        "offline_enabled": device.type == "cashier",
    }
    effective.update(overrides)
    catalog_version = None
    if device.type == "vending":
        catalog = session.scalar(select(CatalogMeta).where(CatalogMeta.id == 1))
        catalog_version = catalog.version if catalog else 0

    return DeviceConfigResponse(
        device_id=device.device_id,
        name=device.name,
        type=device.type,
        mode=(overrides.get("mode") or device.reported_mode) if device.type == "cashier" else None,
        slot_count=device.slot_count if device.type == "vending" else None,
        offline_enabled=bool(effective["offline_enabled"]),
        offline_txn_max=int(effective["offline_txn_max"]),
        offline_card_cap=int(effective["offline_card_cap"]),
        offline_hold_mode=str(effective["offline_hold_mode"]),
        catalog_version=catalog_version,
        server_time_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        device_config_overrides=overrides,
    )
