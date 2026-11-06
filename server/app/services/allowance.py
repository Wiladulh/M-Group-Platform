"""Offline allowance computation using the actual per-device member cache."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Card, Device, Member, OfflineAllowance, Setting, Transaction
from app.services.events import CacheUpdateEvent
from app.services.ledger import InsufficientBalance
from app.services.settings import get_setting

DEFAULT_OFFLINE_CARD_CAP = 50_000
DEFAULT_CACHE_LIMIT = 100


def _device_offline_config(device: Device) -> dict:
    try:
        config = json.loads(device.config_json or "{}")
    except json.JSONDecodeError:
        return {}
    return config if isinstance(config, dict) else {}


def _eligible_offline_devices(session: Session) -> list[tuple[Device, int]]:
    global_cap = get_setting(session, "offline_card_cap", DEFAULT_OFFLINE_CARD_CAP)
    devices = session.scalars(select(Device).where(Device.status == "ACTIVE")).all()
    eligible: list[tuple[Device, int]] = []
    for device in devices:
        config = _device_offline_config(device)
        if not config.get("offline_enabled", False):
            continue
        cap = int(config.get("offline_card_cap", global_cap))
        if cap < 0:
            raise ValueError("offline_card_cap cannot be negative")
        eligible.append((device, cap))
    return eligible


def compute_cached_members_for_device(
    session: Session,
    device_id: int,
    limit: int = DEFAULT_CACHE_LIMIT,
) -> list[int]:
    """Return eligible members ordered by this device's 60-day payment activity, then global recency."""
    if limit <= 0:
        return []
    device = session.get(Device, device_id)
    if device is None or device.status != "ACTIVE":
        return []
    if not _device_offline_config(device).get("offline_enabled", False):
        return []

    cutoff = datetime.now(UTC) - timedelta(days=60)
    on_device = (
        select(
            Transaction.member_id.label("member_id"),
            func.count(Transaction.id).label("payment_count"),
            func.max(Transaction.occurred_at).label("last_payment_at"),
        )
        .join(Member, Member.id == Transaction.member_id)
        .join(Card, Card.member_id == Member.id)
        .where(
            Transaction.device_id == device_id,
            Transaction.type == "PAYMENT",
            Transaction.status == "COMPLETED",
            Transaction.occurred_at >= cutoff,
            Member.status == "ACTIVE",
            Card.status == "ACTIVE",
        )
        .group_by(Transaction.member_id)
        .order_by(
            func.count(Transaction.id).desc(),
            func.max(Transaction.occurred_at).desc(),
            Transaction.member_id.asc(),
        )
        .limit(limit)
    )
    selected = [row.member_id for row in session.execute(on_device)]
    if len(selected) >= limit:
        return selected

    selected_set = set(selected)
    global_recent = (
        select(
            Transaction.member_id.label("member_id"),
            func.max(Transaction.occurred_at).label("last_payment_at"),
        )
        .join(Member, Member.id == Transaction.member_id)
        .join(Card, Card.member_id == Member.id)
        .where(
            Transaction.type == "PAYMENT",
            Transaction.status == "COMPLETED",
            Transaction.device_id.is_not(None),
            Member.status == "ACTIVE",
            Card.status == "ACTIVE",
        )
        .group_by(Transaction.member_id)
        .order_by(
            func.max(Transaction.occurred_at).desc(),
            Transaction.member_id.asc(),
        )
    )
    for row in session.execute(global_recent):
        if row.member_id in selected_set:
            continue
        selected.append(row.member_id)
        selected_set.add(row.member_id)
        if len(selected) >= limit:
            break
    return selected


class AllowanceService:
    """Compute, persist, and enqueue cache snapshots for active members."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _global_cap(self) -> int:
        return get_setting(self.session, "offline_card_cap", DEFAULT_OFFLINE_CARD_CAP)

    def compute_allowances_for_member(self, member_id: int) -> dict[int, int]:
        member = self.session.get(Member, member_id)
        if member is None or member.status != "ACTIVE":
            return {}
        eligible = _eligible_offline_devices(self.session)
        cached_by_device = {
            device.id: compute_cached_members_for_device(self.session, device.id)
            for device, _cap in eligible
        }
        cached_devices = [
            (device, cap)
            for device, cap in eligible
            if member_id in cached_by_device[device.id]
        ]
        count = len(cached_devices)
        if count == 0:
            return {}
        share = member.balance // count
        return {device.id: min(cap, share) for device, cap in cached_devices}

    def apply_allowances(self, member_id: int) -> None:
        """Persist allowances and queue a cache event for after-commit publication."""
        member = self.session.get(Member, member_id)
        if member is None:
            return
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

        cards = self.session.scalars(
            select(Card).where(Card.member_id == member_id, Card.status == "ACTIVE")
        ).all()
        event_snapshot = CacheUpdateEvent(
            member_id=member_id,
            uid_list=[card.uid for card in cards],
            balance_snapshot=member.balance,
            offline_allowance=dict(allowances),
            card_status=cards[0].status if cards else "INACTIVE",
            computed_at_utc=now.isoformat().replace("+00:00", "Z"),
        )
        self.session.info.setdefault("mgt_pending_events", []).append(event_snapshot)


def get_total_allowances(session: Session, member_id: int) -> int:
    """Return the sum of all persisted offline allowances for a member."""
    total = session.scalar(
        select(func.coalesce(func.sum(OfflineAllowance.amount), 0)).where(
            OfflineAllowance.member_id == member_id
        )
    )
    return int(total or 0)


def assert_can_spend_online(session: Session, member_id: int, amount: int) -> None:
    """Enforce the offline allowance hold only when offline_hold_mode is hard."""
    hold_mode = get_setting(session, "offline_hold_mode", "soft")
    if hold_mode != "hard":
        return
    member = session.get(Member, member_id)
    if member is None:
        raise InsufficientBalance("Member does not exist")
    spendable = member.balance - get_total_allowances(session, member_id)
    if amount > spendable:
        raise InsufficientBalance("Online spend exceeds the unreserved member balance")


def compute_allowances_for_member(member_id: int) -> dict[int, int]:
    """Compute allowance map using the configured application database."""
    with SessionLocal() as session:
        return AllowanceService(session).compute_allowances_for_member(member_id)


def apply_allowances(member_id: int) -> None:
    """Persist allowances using the configured application database."""
    with SessionLocal.begin() as session:
        AllowanceService(session).apply_allowances(member_id)
