"""Online cashier payment and balance-check application services."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import AuditLog, Card, Member, Transaction
from app.schemas.payment import (
    BalanceCheckRequest,
    BalanceCheckResponse,
    PaymentRequest,
    PaymentResponse,
)
from app.security.device_auth import DeviceAuthInfo
from app.security.pins import verify_pin
from app.services.allowance import assert_can_spend_online
from app.services.cache_version import bump_member_cache_version
from app.services.ledger import IdempotencyConflict, InsufficientBalance, LedgerService

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _check_clock(ts: int, now: datetime) -> None:
    if abs(int(now.timestamp()) - ts) > 300:
        raise DomainError(code="CLOCK_SKEW", status_code=400)


def _load_card_member(session: Session, uid: str) -> tuple[Card, Member]:
    card = session.scalar(select(Card).where(Card.uid == uid.upper()))
    if card is None:
        raise DomainError(code="CARD_UNKNOWN", status_code=422)
    if card.status == "LOCKED":
        raise DomainError(code="CARD_LOCKED", status_code=422)
    if card.status != "ACTIVE":
        raise DomainError(code="CARD_INACTIVE", status_code=422)
    member = session.get(Member, card.member_id)
    if member is None or member.status != "ACTIVE":
        raise DomainError(code="MEMBER_SUSPENDED", status_code=422)
    return card, member


def _check_pin(session: Session, card_id: int, pin: str, pin_hash: str) -> None:
    if verify_pin(pin, pin_hash):
        return
    # End the read transaction before committing the security counter independently.
    session.rollback()
    locked = False
    attempts_left = 0
    with session.begin():
        card = session.get(Card, card_id)
        if card is None:
            raise DomainError(code="CARD_UNKNOWN", status_code=422)
        card.pin_fail_count += 1
        if card.pin_fail_count >= 3:
            card.status = "LOCKED"
            bump_member_cache_version(session, card.member_id)
            locked = True
        else:
            attempts_left = max(0, 3 - card.pin_fail_count)
    if locked:
        raise DomainError(code="CARD_LOCKED", status_code=422)
    raise DomainError(
        code="INVALID_PIN",
        status_code=422,
        details={"attempts_left": attempts_left},
    )


def _payment_response(txn: Transaction, member: Member) -> PaymentResponse:
    return PaymentResponse(
        txn_uuid=txn.txn_uuid,
        member_code=member.member_code,
        full_name=member.full_name,
        amount=txn.amount,
        balance_before=txn.balance_before,
        balance_after=txn.balance_after,
        status=txn.status,
        occurred_at_utc=_iso_utc(txn.occurred_at),
    )


class PaymentService:
    """Compose card validation, PIN policy, ledger debit, and audit writes."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.ledger = LedgerService(session)

    def process_payment(
        self,
        session: Session,
        device_auth: DeviceAuthInfo,
        payload: PaymentRequest,
    ) -> PaymentResponse:
        now = _utc_now()
        _check_clock(payload.ts, now)
        card, member = _load_card_member(session, payload.uid)
        _check_pin(session, card.id, payload.pin, card.pin_hash)

        # Close the SELECT autobegin before opening the write transaction.
        card_id, member_id = card.id, member.id
        session.rollback()
        existing = session.scalar(
            select(Transaction).where(Transaction.txn_uuid == payload.txn_uuid)
        )
        if existing is not None:
            matches = (
                existing.member_id == member_id
                and existing.card_id == card_id
                and existing.device_id == device_auth.id
                and existing.type == "PAYMENT"
                and existing.direction == "DEBIT"
                and existing.source == "ONLINE"
                and existing.amount == payload.amount
                and existing.performed_by_type == "DEVICE"
                and existing.performed_by_id == device_auth.device_id
            )
            if not matches:
                session.rollback()
                raise DomainError(code="DUPLICATE_TXN", status_code=409)
            result_member = session.get(Member, member_id)
            response = _payment_response(existing, result_member)
            session.rollback()
            return response
        session.rollback()

        try:
            with session.begin():
                current_card = session.get(Card, card_id)
                current_member = session.get(Member, member_id)
                if current_card is None or current_member is None:
                    raise DomainError(code="CARD_UNKNOWN", status_code=422)
                current_card.pin_fail_count = 0
                assert_can_spend_online(session, member_id, payload.amount)
                txn = self.ledger._debit_internal(
                    member_id=member_id,
                    amount=payload.amount,
                    txn_uuid=payload.txn_uuid,
                    card_id=card_id,
                    device_id=device_auth.id,
                    type="PAYMENT",
                    source="ONLINE",
                    performed_by_type="DEVICE",
                    performed_by_id=device_auth.device_id,
                    occurred_at=now,
                )
                response = _payment_response(txn, current_member)
            logger.info(
                "payment_completed uid=%s txn_uuid=%s device_id=%s",
                payload.uid,
                payload.txn_uuid,
                device_auth.device_id,
            )
            return response
        except InsufficientBalance as exc:
            raise DomainError(code="INSUFFICIENT_BALANCE", status_code=422) from exc
        except IdempotencyConflict as exc:
            if exc.original is None:
                raise DomainError(code="DUPLICATE_TXN", status_code=409) from exc
            with session.begin():
                original_member = session.get(Member, exc.original.member_id)
                return _payment_response(exc.original, original_member)

    def process_balance_check(
        self,
        session: Session,
        device_auth: DeviceAuthInfo,
        payload: BalanceCheckRequest,
        *,
        ip: str | None = None,
    ) -> BalanceCheckResponse:
        now = _utc_now()
        _check_clock(payload.ts, now)
        card, member = _load_card_member(session, payload.uid)
        _check_pin(session, card.id, payload.pin, card.pin_hash)
        card_id, member_id = card.id, member.id
        session.rollback()
        with session.begin():
            current_card = session.get(Card, card_id)
            current_member = session.get(Member, member_id)
            if current_card is None or current_member is None:
                raise DomainError(code="CARD_UNKNOWN", status_code=422)
            current_card.pin_fail_count = 0
            self.session.add(
                AuditLog(
                    actor_type="DEVICE",
                    actor_id=device_auth.device_id,
                    action="balance_check",
                    entity="member",
                    entity_id=str(member_id),
                    before_json=None,
                    after_json=None,
                    ip=ip,
                )
            )
            result = BalanceCheckResponse(
                member_code=current_member.member_code,
                full_name=current_member.full_name,
                balance=current_member.balance,
                as_of_utc=_iso_utc(now),
            )
        return result
