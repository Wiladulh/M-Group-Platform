"""Cashier top-up orchestration with independent PIN lockout commits."""
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import AuditLog, Card, Device, Member, Operator, OperatorDevice, TopUpRequest, Transaction
from app.schemas.topup import TopupRequestPayload, TopupResponse
from app.security.device_auth import DeviceAuthInfo
from app.security.operator_pin import verify_operator_pin
from app.security.pins import verify_pin
from app.services.ledger import IdempotencyConflict, LedgerService
from app.services.settings import get_setting


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat().replace("+00:00", "Z")


def _validate_amount(session: Session, amount: int) -> None:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise DomainError(code="VALIDATION_ERROR", status_code=400, details={"detail": "Nominal harus berupa bilangan Rupiah positif"})
    if amount % 1000:
        raise DomainError(code="VALIDATION_ERROR", status_code=400, details={"detail": "Nominal harus kelipatan Rp1.000"})
    minimum = int(get_setting(session, "topup_min", 5000))
    maximum = int(get_setting(session, "topup_max", 1_000_000))
    if amount < minimum:
        raise DomainError(code="VALIDATION_ERROR", status_code=400, details={"detail": f"Minimal top-up Rp{minimum:,}".replace(",", ".")})
    if amount > maximum:
        raise DomainError(code="VALIDATION_ERROR", status_code=400, details={"detail": f"Maksimal top-up Rp{maximum:,}".replace(",", ".")})


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


def _verify_member_pin(session: Session, card_id: int, pin: str, pin_hash: str) -> None:
    if verify_pin(pin, pin_hash):
        return
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
            locked = True
        else:
            attempts_left = 3 - card.pin_fail_count
    if locked:
        raise DomainError(code="CARD_LOCKED", status_code=422)
    raise DomainError(code="INVALID_PIN", status_code=422, details={"attempts_left": attempts_left})


def _operator_failure(session: Session, operator_id: int) -> None:
    session.rollback()
    locked = False
    with session.begin():
        operator = session.get(Operator, operator_id)
        if operator is None:
            raise DomainError(code="OPERATOR_INVALID", status_code=422)
        operator.pin_fail_count += 1
        if operator.pin_fail_count >= 5:
            operator.locked_until = _utc_now() + timedelta(minutes=15)
            locked = True
        attempts_left = max(0, 5 - operator.pin_fail_count)
    if locked:
        raise DomainError(code="OPERATOR_LOCKED", status_code=422, details={"attempts_left": 0})
    raise DomainError(code="OPERATOR_INVALID", status_code=422, details={"attempts_left": attempts_left})


def _same_request(row: TopUpRequest, member_id: int, amount: int, device_id: int, operator_no: int) -> bool:
    return (
        row.member_id == member_id
        and row.amount == amount
        and row.device_id == device_id
        and row.source == "CASHIER"
        and row.processed_by_type == "OPERATOR"
        and row.processed_by_id == str(operator_no)
    )


def _response(row: TopUpRequest, txn: Transaction, member: Member, operator: Operator, device_id: str) -> TopupResponse:
    return TopupResponse(
        txn_uuid=row.request_uuid,
        member_code=member.member_code,
        full_name=member.full_name,
        amount=row.amount,
        balance_before=txn.balance_before,
        balance_after=txn.balance_after,
        status=row.status,
        occurred_at_utc=_iso(txn.occurred_at),
        operator_code=operator.operator_no,
        operator_name=operator.nama,
        device_id=device_id,
    )


def process_cashier_topup(
    session: Session,
    device_auth: DeviceAuthInfo,
    payload: TopupRequestPayload,
    *,
    ip: str | None = None,
) -> TopupResponse:
    """Validate and atomically credit one cashier top-up."""
    now = _utc_now()
    if abs(int(now.timestamp()) - payload.ts) > 300:
        raise DomainError(code="CLOCK_SKEW", status_code=400)
    if device_auth.type != "cashier":
        raise DomainError(code="VALIDATION_ERROR", status_code=400, details={"detail": "Top-up hanya di Cashier"})

    card, member = _load_card_member(session, payload.uid)
    card_id, member_id = card.id, member.id
    operator = session.scalar(select(Operator).where(Operator.operator_no == payload.operator_no))
    if operator is None or not operator.is_active:
        raise DomainError(code="OPERATOR_INVALID", status_code=422)
    if operator.locked_until is not None and _aware(operator.locked_until) > now:
        raise DomainError(code="OPERATOR_LOCKED", status_code=422)

    operator_id, operator_no = operator.id, operator.operator_no
    if not verify_operator_pin(payload.operator_pin, operator.operator_pin_hash):
        _operator_failure(session, operator_id)
    if session.scalar(
        select(OperatorDevice.id).where(
            OperatorDevice.operator_id == operator_id,
            OperatorDevice.device_id == device_auth.id,
        )
    ) is None:
        session.rollback()
        raise DomainError(
            code="OPERATOR_INVALID",
            status_code=422,
            message="Operator tidak terikat ke unit ini",
        )

    _verify_member_pin(session, card_id, payload.pin, card.pin_hash)
    _validate_amount(session, payload.amount)
    session.rollback()

    existing = session.scalar(select(TopUpRequest).where(TopUpRequest.request_uuid == payload.txn_uuid))
    if existing is not None:
        if not _same_request(existing, member_id, payload.amount, device_auth.id, operator_no):
            session.rollback()
            raise DomainError(code="DUPLICATE_TXN", status_code=409)
        txn = session.get(Transaction, existing.txn_id)
        current_member = session.get(Member, member_id)
        current_operator = session.get(Operator, operator_id)
        result = _response(existing, txn, current_member, current_operator, device_auth.device_id)
        session.rollback()
        return result
    session.rollback()

    try:
        with session.begin():
            current_card = session.get(Card, card_id)
            current_member = session.get(Member, member_id)
            current_operator = session.get(Operator, operator_id)
            if current_card is None or current_member is None or current_operator is None:
                raise DomainError(code="CARD_UNKNOWN", status_code=422)
            before = current_member.balance
            if current_card.pin_fail_count:
                current_card.pin_fail_count = 0
            if current_operator.pin_fail_count:
                current_operator.pin_fail_count = 0
            txn = LedgerService(session)._credit_internal(
                member_id=member_id,
                amount=payload.amount,
                txn_uuid=payload.txn_uuid,
                device_id=device_auth.id,
                type="TOPUP",
                source="CASHIER",
                performed_by_type="OPERATOR",
                performed_by_id=str(operator_no),
            )
            row = TopUpRequest(
                request_uuid=payload.txn_uuid,
                member_id=member_id,
                amount=payload.amount,
                status="COMPLETED",
                source="CASHIER",
                device_id=device_auth.id,
                processed_by_type="OPERATOR",
                processed_by_id=str(operator_no),
                txn_id=txn.id,
                note=None,
            )
            session.add(row)
            session.flush()
            session.add(AuditLog(
                actor_type="OPERATOR",
                actor_id=str(operator_no),
                action="topup.cashier",
                entity="topup_request",
                entity_id=str(row.id),
                before_json=json.dumps({"member_balance": before}, separators=(",", ":")),
                after_json=json.dumps({"member_balance": txn.balance_after}, separators=(",", ":")),
                ip=ip,
            ))
            result = _response(row, txn, current_member, current_operator, device_auth.device_id)
        return result
    except IdempotencyConflict as exc:
        if exc.original is None:
            raise DomainError(code="DUPLICATE_TXN", status_code=409) from exc
        raise DomainError(code="DUPLICATE_TXN", status_code=409) from exc
