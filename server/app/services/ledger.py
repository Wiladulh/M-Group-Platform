"""Atomic, append-only member balance ledger service."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Member, Transaction


class LedgerError(Exception):
    """Base class for ledger domain errors."""


class InsufficientBalance(LedgerError):
    """Raised when an atomic debit cannot be applied."""


class InvalidAmount(LedgerError):
    """Raised when an amount is not a positive Rupiah integer."""


class IdempotencyConflict(LedgerError):
    """Raised for a reused idempotency key."""

    def __init__(self, message: str, *, original: Transaction | None = None, conflict: bool = False):
        super().__init__(message)
        self.original = original
        self.conflict = conflict


class LedgerService:
    """Session-bound ledger service; each public mutation owns one DB transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _validate_amount(amount: int) -> None:
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise InvalidAmount("Amount must be a positive integer Rupiah value")

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _payload_matches(existing: Transaction, payload: dict) -> bool:
        fields = (
            "member_id", "card_id", "device_id", "type", "amount", "direction",
            "source", "items_json", "note", "performed_by_type", "performed_by_id",
            "card_inactive_at_sync",
        )
        if not all(getattr(existing, key) == payload[key] for key in fields):
            return False
        expected_at = payload.get("occurred_at")
        if expected_at is not None:
            stored_at = existing.occurred_at
            if stored_at.tzinfo is None:
                stored_at = stored_at.replace(tzinfo=UTC)
            if stored_at != expected_at:
                return False
        if "ref_txn_id" in payload and existing.ref_txn_id != payload["ref_txn_id"]:
            return False
        return True

    def _check_idempotency(self, txn_uuid: str, payload: dict) -> None:
        existing = self.session.scalar(
            select(Transaction).where(Transaction.txn_uuid == txn_uuid)
        )
        if existing is None:
            return
        if self._payload_matches(existing, payload):
            # Preserve the loaded row through the rollback caused by the domain exception.
            self.session.expunge(existing)
            raise IdempotencyConflict(
                "Identical transaction already exists", original=existing, conflict=False
            )
        raise IdempotencyConflict("Transaction UUID payload conflict", conflict=True)

    def _change_balance(self, member_id: int, amount: int, *, debit: bool) -> tuple[int, int]:
        self._validate_amount(amount)
        if debit:
            stmt = (
                update(Member)
                .where(Member.id == member_id, Member.balance >= amount)
                .values(balance=Member.balance - amount)
                .returning(Member.balance)
            )
        else:
            stmt = (
                update(Member)
                .where(Member.id == member_id)
                .values(balance=Member.balance + amount)
                .returning(Member.balance)
            )
        after = self.session.execute(stmt).scalar_one_or_none()
        if after is None:
            if debit:
                raise InsufficientBalance("Member balance is insufficient")
            raise LedgerError(f"Member {member_id} does not exist")
        if after < 0:
            raise LedgerError("Golden balance invariant violated")
        return (after + amount, after) if debit else (after - amount, after)

    def _insert(self, *, txn_uuid: str, member_id: int, amount: int, direction: str,
                type: str, source: str, before: int, after: int,
                performed_by_type: str, performed_by_id: str | None,
                card_id: int | None = None, device_id: int | None = None,
                items_json: str | None = None, note: str | None = None,
                occurred_at: datetime | None = None,
                card_inactive_at_sync: bool = False,
                ref_txn_id: int | None = None, status: str = "COMPLETED") -> Transaction:
        row = Transaction(
            txn_uuid=txn_uuid, member_id=member_id, card_id=card_id, device_id=device_id,
            type=type, amount=amount, direction=direction, balance_before=before,
            balance_after=after, status=status, source=source,
            occurred_at=self._utc(occurred_at), items_json=items_json,
            ref_txn_id=ref_txn_id, note=note, performed_by_type=performed_by_type,
            performed_by_id=performed_by_id, card_inactive_at_sync=card_inactive_at_sync,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def debit(self, member_id: int, amount: int, *, txn_uuid: str, card_id: int | None,
              device_id: int | None, type: str, source: str, items_json: str | None = None,
              note: str | None = None, occurred_at: datetime | None = None,
              performed_by_type: str, performed_by_id: str | None,
              card_inactive_at_sync: bool = False) -> Transaction:
        self._validate_amount(amount)
        occurred_at = self._utc(occurred_at) if occurred_at is not None else None
        payload = dict(member_id=member_id, card_id=card_id, device_id=device_id, type=type,
                       amount=amount, direction="DEBIT", source=source, items_json=items_json,
                       note=note, occurred_at=occurred_at, performed_by_type=performed_by_type,
                       performed_by_id=performed_by_id,
                       card_inactive_at_sync=card_inactive_at_sync)
        with self.session.begin():
            self._check_idempotency(txn_uuid, payload)
            before, after = self._change_balance(member_id, amount, debit=True)
            row = self._insert(txn_uuid=txn_uuid, member_id=member_id, amount=amount,
                direction="DEBIT", type=type, source=source, before=before, after=after,
                performed_by_type=performed_by_type, performed_by_id=performed_by_id,
                card_id=card_id, device_id=device_id, items_json=items_json, note=note,
                occurred_at=occurred_at, card_inactive_at_sync=card_inactive_at_sync)
            self._refresh_allowances(member_id)
            return row

    def credit(self, member_id: int, amount: int, *, txn_uuid: str,
               card_id: int | None = None, device_id: int | None = None,
               type: str = "TOPUP", source: str = "ADMIN",
               items_json: str | None = None, note: str | None = None,
               occurred_at: datetime | None = None, performed_by_type: str = "ADMIN",
               performed_by_id: str | None = None, card_inactive_at_sync: bool = False,
               ref_txn_id: int | None = None) -> Transaction:
        self._validate_amount(amount)
        if type not in {"TOPUP", "REFUND", "ADJUSTMENT"}:
            raise LedgerError("Credit supports TOPUP, REFUND, or ADJUSTMENT only")
        occurred_at = self._utc(occurred_at) if occurred_at is not None else None
        payload = dict(member_id=member_id, card_id=card_id, device_id=device_id, type=type,
                       amount=amount, direction="CREDIT", source=source, items_json=items_json,
                       note=note, occurred_at=occurred_at, ref_txn_id=ref_txn_id,
                       performed_by_type=performed_by_type, performed_by_id=performed_by_id,
                       card_inactive_at_sync=card_inactive_at_sync)
        with self.session.begin():
            self._check_idempotency(txn_uuid, payload)
            before, after = self._change_balance(member_id, amount, debit=False)
            row = self._insert(txn_uuid=txn_uuid, member_id=member_id, amount=amount,
                direction="CREDIT", type=type, source=source, before=before, after=after,
                performed_by_type=performed_by_type, performed_by_id=performed_by_id,
                card_id=card_id, device_id=device_id, items_json=items_json, note=note,
                occurred_at=occurred_at, card_inactive_at_sync=card_inactive_at_sync,
                ref_txn_id=ref_txn_id)
            self._refresh_allowances(member_id)
            return row

    def reverse(self, original_txn_id: int, *, reason: str,
                performed_by_type: str, performed_by_id: str | None) -> Transaction:
        with self.session.begin():
            original = self.session.get(Transaction, original_txn_id)
            if original is None:
                raise LedgerError(f"Transaction {original_txn_id} does not exist")
            if self.session.scalar(select(Transaction.id).where(
                Transaction.ref_txn_id == original_txn_id
            )) is not None:
                raise LedgerError("Transaction has already been reversed")
            debit = original.direction == "CREDIT"
            before, after = self._change_balance(original.member_id, original.amount, debit=debit)
            row = self._insert(txn_uuid=str(uuid4()), member_id=original.member_id,
                amount=original.amount, direction="DEBIT" if debit else "CREDIT",
                type="ADJUSTMENT", source="ADMIN", before=before, after=after,
                performed_by_type=performed_by_type, performed_by_id=performed_by_id,
                card_id=original.card_id, device_id=original.device_id, note=reason,
                ref_txn_id=original.id)
            self._refresh_allowances(original.member_id)
            return row

    def _set_status(self, txn_id: int, status: str, allowed: set[str]) -> None:
        with self.session.begin():
            row = self.session.get(Transaction, txn_id)
            if row is None or row.status not in allowed:
                raise LedgerError(f"Invalid transaction status transition to {status}")
            row.status = status

    def set_pending_dispense(self, txn_id: int) -> None:
        self._set_status(txn_id, "PENDING_DISPENSE", {"COMPLETED"})

    def complete_pending_dispense(self, txn_id: int) -> None:
        self._set_status(txn_id, "COMPLETED", {"PENDING_DISPENSE"})

    def fail_pending_dispense(self, txn_id: int, auto_refund: bool = True) -> Transaction:
        with self.session.begin():
            original = self.session.get(Transaction, txn_id)
            if original is None or original.status != "PENDING_DISPENSE":
                raise LedgerError("Transaction is not pending dispense")
            original.status = "DISPENSE_FAILED"
            if not auto_refund:
                return original
            before, after = self._change_balance(original.member_id, original.amount, debit=False)
            row = self._insert(txn_uuid=str(uuid4()), member_id=original.member_id,
                amount=original.amount, direction="CREDIT", type="REFUND", source="ADMIN",
                before=before, after=after, performed_by_type="SYSTEM", performed_by_id="SYSTEM",
                card_id=original.card_id, device_id=original.device_id,
                note=f"Automatic refund for failed dispense transaction {original.id}",
                ref_txn_id=original.id)
            self._refresh_allowances(original.member_id)
            return row

    def _refresh_allowances(self, member_id: int) -> None:
        from app.services.allowance import AllowanceService

        AllowanceService(self.session).apply_allowances(member_id)
