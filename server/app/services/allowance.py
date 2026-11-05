"""Minimum viable offline allowance calculation (cache and WS flow is completed in P9)."""

import json
from datetime import UTC, datetime

from app.db import SessionLocal
from app.models import Device, Member, OfflineAllowance, Setting
from sqlalchemy import select
from sqlalchemy.orm import Session


DEFAULT_OFFLINE_CARD_CAP = 50_000


class AllowanceService:
    """Compute and persist each active offline-capable device's member allowance."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _global_cap(self) -> int:
        value = self.session.scalar(
            select(Setting.value).where(Setting.key == "offline_card_cap")
        )
        return int(value) if value is not None else DEFAULT_OFFLINE_CARD_CAP

    def compute_allowances_for_member(self, member_id: int) -> dict[int, int]:
        member = self.session.get(Member, member_id)
        if member is None or member.status != "ACTIVE":
            return {}
        devices = self.session.scalars(
            select(Device).where(Device.status == "ACTIVE")
        ).all()
        eligible: list[tuple[Device, int]] = []
        global_cap = self._global_cap()
        for device in devices:
            config = json.loads(device.config_json or "{}")
            if not config.get("offline_enabled", False):
                continue
            cap = int(config.get("offline_card_cap", global_cap))
            if cap < 0:
                raise ValueError("offline_card_cap cannot be negative")
            eligible.append((device, cap))
        count = len(eligible)
        if count == 0:
            return {}
        return {
            device.id: min(cap, member.balance // count)
            for device, cap in eligible
        }

    def apply_allowances(self, member_id: int) -> None:
        """Persist allowance rows; P9 adds ordered WebSocket cache updates."""
        allowances = self.compute_allowances_for_member(member_id)
        now = datetime.now(UTC)
        existing_rows = self.session.scalars(
            select(OfflineAllowance).where(OfflineAllowance.member_id == member_id)
        ).all()
        existing_by_device = {row.device_id: row for row in existing_rows}
        for device_id, row in existing_by_device.items():
            if device_id not in allowances:
                row.amount = 0
                row.computed_at = now
                row.version += 1
        for device_id, amount in allowances.items():
            row = existing_by_device.get(device_id)
            if row is None:
                self.session.add(
                    OfflineAllowance(
                        member_id=member_id,
                        device_id=device_id,
                        amount=amount,
                        computed_at=now,
                        version=1,
                    )
                )
            else:
                row.amount = amount
                row.computed_at = now
                row.version += 1
        self.session.flush()


def compute_allowances_for_member(member_id: int) -> dict[int, int]:
    """Compute allowance map using the configured application database."""
    with SessionLocal() as session:
        return AllowanceService(session).compute_allowances_for_member(member_id)


def apply_allowances(member_id: int) -> None:
    """Persist allowances using the configured application database."""
    with SessionLocal.begin() as session:
        AllowanceService(session).apply_allowances(member_id)
