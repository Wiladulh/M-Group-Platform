"""Best-effort device online/offline webhook notifications."""

import asyncio
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _post(payload: dict) -> None:
    url = get_settings().alert_webhook_url
    if not url:
        return

    async def send() -> None:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(url, json=payload)
        except Exception:
            logger.warning("device_alert_webhook_failed event=%s", payload.get("event"))

    try:
        asyncio.get_running_loop().create_task(send())
    except RuntimeError:
        logger.debug("device_alert_no_running_loop")


def fire_device_offline(device, since_utc) -> None:
    _post({"device": device.device_id, "event": "offline", "since": since_utc.isoformat()})


def fire_device_online(device) -> None:
    _post({"device": device.device_id, "event": "online"})
