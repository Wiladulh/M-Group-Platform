"""Sequential, idempotent offline batch synchronization."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Card, Device, Member, OfflineAllowance, PendingSyncLog, Product,
    ShortfallRecord, Transaction,
)
from app.schemas.sync import (
    CacheEntryDelta, SyncBatch, SyncItem, SyncItemResult, SyncResponse,
)
from app.services.allowance import AllowanceService
from app.services.cache_version import (
    bump_member_cache_version, get_member_cache_version,
)
from app.services.events import CardStatusChangedEvent
from app.services.ledger import InsufficientBalance, LedgerService

REFUND_NAMESPACE = UUID("5f5f0e1a-6c91-4a0a-a5d2-4e35cfc3d66a")


def _utc_from_epoch(value: int) -> datetime:
    return datetime.fromtimestamp(value, UTC)


def _items_json(item: SyncItem, product_name: str | None = None) -> str | None:
    if item.slot_no is None and item.product_id is None:
        return None
    data = {"slot_no": item.slot_no, "product_id": item.product_id}
    if product_name is not None:
        data["name"] = product_name
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _payload_identical(row: Transaction, item: SyncItem, device: Device,
                       member_id: int, card_id: int, items_json: str | None) -> bool:
    occurred = _utc_from_epoch(item.offline_ts)
    stored = row.occurred_at
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=UTC)
    return (
        row.member_id == member_id
        and row.card_id == card_id
        and row.device_id == device.id
        and row.type == "PAYMENT"
        and row.amount == item.price
        and row.direction == "DEBIT"
        and row.source == "OFFLINE_SYNC"
        and row.items_json == items_json
        and stored == occurred
        and row.performed_by_type == "DEVICE"
        and row.performed_by_id == device.device_id
    )


class SyncService:
    """Apply one device batch in a single transaction, preserving event order."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.ledger = LedgerService(session)

    def _cache_delta(self, device_id: int, member_ids: set[int]) -> list[CacheEntryDelta]:
        if not member_ids:
            return []
        rows = self.session.execute(
            select(OfflineAllowance, Member, Card)
            .join(Member, Member.id == OfflineAllowance.member_id)
            .join(Card, Card.member_id == Member.id)
            .where(
                OfflineAllowance.device_id == device_id,
                Member.id.in_(member_ids),
            )
            .order_by(Member.member_code, Card.uid)
        ).all()
        delta = []
        for allowance, member, card in rows:
            delta.append(CacheEntryDelta(
                uid=card.uid,
                member_code=member.member_code,
                name=member.full_name,
                balance_snapshot=member.balance,
                snapshot_ts=(allowance.computed_at.replace(tzinfo=UTC) if allowance.computed_at.tzinfo is None else allowance.computed_at.astimezone(UTC)).isoformat().replace("+00:00", "Z"),
                offline_allowance=allowance.amount,
                card_status=card.status,
                entry_version=allowance.version,
            ))
        return delta

    def _reject_row(
        self, item: SyncItem, *, member: Member, card: Card | None,
        device: Device, reason: str, card_inactive: bool, items_json: str | None,
    ) -> Transaction:
        balance = member.balance
        row = Transaction(
            txn_uuid=item.txn_uuid,
            member_id=member.id,
            card_id=card.id if card else None,
            device_id=device.id,
            type="PAYMENT",
            amount=item.price,
            direction="DEBIT",
            balance_before=balance,
            balance_after=balance,
            status="REJECTED",
            reject_reason=reason,
            source="OFFLINE_SYNC",
            occurred_at=_utc_from_epoch(item.offline_ts),
            items_json=items_json,
            performed_by_type="DEVICE",
            performed_by_id=device.device_id,
            card_inactive_at_sync=card_inactive,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _process_item(self, device: Device, item: SyncItem) -> tuple[SyncItemResult, int | None]:
        existing = self.session.scalar(
            select(Transaction).where(Transaction.txn_uuid == item.txn_uuid)
        )
        if existing is not None:
            card = self.session.get(Card, existing.card_id) if existing.card_id else None
            member = self.session.get(Member, existing.member_id)
            product_name = None
            if item.product_id is not None:
                product = self.session.get(Product, item.product_id)
                product_name = product.name if product else None
            payload_json = _items_json(item, product_name)
            if member is not None and card is not None and _payload_identical(
                existing, item, device, member.id, card.id, payload_json
            ):
                return SyncItemResult(
                    txn_uuid=item.txn_uuid, status="DUPLICATE",
                    balance_after=existing.balance_after,
                ), member.id
            return SyncItemResult(
                txn_uuid=item.txn_uuid, status="REJECTED",
                reason="DUPLICATE_TXN_CONFLICT",
                balance_after=None,
            ), None

        card = self.session.scalar(select(Card).where(Card.uid == item.uid))
        if card is None:
            # transactions.member_id is NOT NULL: preserve this rejection in detail_json only.
            return SyncItemResult(
                txn_uuid=item.txn_uuid, status="REJECTED", reason="CARD_UNKNOWN"
            ), None

        member = self.session.get(Member, card.member_id)
        if member is None:
            return SyncItemResult(
                txn_uuid=item.txn_uuid, status="REJECTED", reason="CARD_UNKNOWN"
            ), None

        inactive = card.status in {"INACTIVE", "LOCKED"}
        product_name = None
        if item.product_id is not None:
            product = self.session.get(Product, item.product_id)
            product_name = product.name if product else None
        serialized_items = _items_json(item, product_name)

        if member.status == "SUSPENDED":
            self._reject_row(
                item, member=member, card=card, device=device,
                reason="MEMBER_SUSPENDED", card_inactive=inactive,
                items_json=serialized_items,
            )
            result = SyncItemResult(
                txn_uuid=item.txn_uuid, status="REJECTED", reason="MEMBER_SUSPENDED"
            )
            affected = member.id
        elif item.offline_ts > int(datetime.now(UTC).timestamp()) + 300:
            self._reject_row(
                item, member=member, card=card, device=device,
                reason="CLOCK_SKEW_OFFLINE", card_inactive=inactive,
                items_json=serialized_items,
            )
            result = SyncItemResult(
                txn_uuid=item.txn_uuid, status="REJECTED", reason="CLOCK_SKEW_OFFLINE"
            )
            affected = member.id
        else:
            try:
                original = self.ledger._debit_internal(
                    member.id, item.price,
                    txn_uuid=item.txn_uuid,
                    card_id=card.id,
                    device_id=device.id,
                    type="PAYMENT",
                    source="OFFLINE_SYNC",
                    items_json=serialized_items,
                    occurred_at=_utc_from_epoch(item.offline_ts),
                    performed_by_type="DEVICE",
                    performed_by_id=device.device_id,
                    card_inactive_at_sync=inactive,
                )
            except InsufficientBalance:
                self._reject_row(
                    item, member=member, card=card, device=device,
                    reason="INSUFFICIENT_AT_SYNC", card_inactive=inactive,
                    items_json=serialized_items,
                )
                shortfall = ShortfallRecord(
                    txn_uuid=item.txn_uuid,
                    device_id=device.id,
                    member_id=member.id,
                    amount=item.price,
                    occurred_at=_utc_from_epoch(item.offline_ts),
                    reason="insufficient at sync",
                    status="OPEN",
                )
                self.session.add(shortfall)
                self.session.flush()
                result = SyncItemResult(
                    txn_uuid=item.txn_uuid, status="REJECTED",
                    reason="INSUFFICIENT_AT_SYNC", shortfall_id=shortfall.id,
                )
                affected = member.id
            else:
                if item.dispense_result == "failed":
                    original.status = "DISPENSE_FAILED"
                    refund_uuid = str(uuid5(REFUND_NAMESPACE, item.txn_uuid))
                    self.ledger._credit_internal(
                        member.id, item.price,
                        txn_uuid=refund_uuid,
                        card_id=card.id,
                        device_id=device.id,
                        type="REFUND",
                        source="ADMIN",
                        note=f"Offline dispense failed for {item.txn_uuid}",
                        performed_by_type="SYSTEM",
                        performed_by_id="SYSTEM",
                        ref_txn_id=original.id,
                    )
                elif device.type == "vending" and item.dispense_result in {None, "unknown"}:
                    original.status = "PENDING_DISPENSE"
                else:
                    original.status = "COMPLETED"
                result = SyncItemResult(
                    txn_uuid=item.txn_uuid, status="ACCEPTED",
                    balance_after=original.balance_after,
                )
                affected = member.id

        if item.pin_fail_events > 0:
            card.pin_fail_count += item.pin_fail_events
            if card.pin_fail_count >= 3 and card.status != "LOCKED":
                card.status = "LOCKED"
                bump_member_cache_version(self.session)
                self.session.info.setdefault("mgt_pending_events", []).append(
                    CardStatusChangedEvent(uid=card.uid, status="LOCKED")
                )
                affected = member.id

        return result, affected

    def process_batch(self, device, batch: SyncBatch) -> SyncResponse:
        """Persist all item outcomes and batch idempotency metadata atomically."""
        with self.session.begin():
            previous = self.session.scalar(
                select(PendingSyncLog).where(
                    PendingSyncLog.device_id == device.id,
                    PendingSyncLog.batch_uuid == batch.batch_uuid,
                )
            )
            if previous is not None:
                prior = json.loads(previous.detail_json or "{}")
                results = [
                    SyncItemResult(**{**entry, "status": "DUPLICATE"})
                    for entry in prior.get("results", [])
                ]
                return SyncResponse(
                    batch_uuid=batch.batch_uuid,
                    total=previous.total,
                    accepted=0,
                    rejected=0,
                    results=results,
                    cache_version=get_member_cache_version(self.session),
                    member_cache_delta=[],
                )

            log_row = PendingSyncLog(
                device_id=device.id,
                batch_uuid=batch.batch_uuid,
                received_at=datetime.now(UTC),
                total=len(batch.items),
                accepted=0,
                rejected=0,
                detail_json=None,
            )
            self.session.add(log_row)
            self.session.flush()

            results_by_uuid: dict[str, tuple[SyncItemResult, int | None]] = {}
            affected_members: set[int] = set()
            for item in sorted(batch.items, key=lambda entry: entry.offline_ts):
                result, member_id = self._process_item(device, item)
                results_by_uuid[item.txn_uuid] = (result, member_id)
                if member_id is not None:
                    affected_members.add(member_id)
                self.session.flush()

            for member_id in sorted(affected_members):
                AllowanceService(self.session).apply_allowances(member_id)

            ordered_results = [
                results_by_uuid[item.txn_uuid][0] for item in batch.items
            ]
            accepted = sum(result.status == "ACCEPTED" for result in ordered_results)
            rejected = sum(result.status == "REJECTED" for result in ordered_results)
            log_row.accepted = accepted
            log_row.rejected = rejected
            log_row.detail_json = json.dumps(
                {
                    "results": [result.model_dump() for result in ordered_results],
                    "items": [item.model_dump() for item in batch.items],
                },
                separators=(",", ":"),
            )
            self.session.flush()
            cache_version = get_member_cache_version(self.session)
            delta = self._cache_delta(device.id, affected_members)
            return SyncResponse(
                batch_uuid=batch.batch_uuid,
                total=len(batch.items),
                accepted=accepted,
                rejected=rejected,
                results=ordered_results,
                cache_version=cache_version,
                member_cache_delta=delta,
            )
