"""Cashier payment, balance-check, and transaction-status endpoints."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import DomainError
from app.models import Transaction
from app.schemas.payment import (
    BalanceCheckRequest,
    BalanceCheckResponse,
    PaymentRequest,
    PaymentResponse,
    TransactionStatusResponse,
)
from app.security.device_auth import DeviceAuthInfo, require_device
from app.services.payment import PaymentService, _iso_utc

router = APIRouter(prefix="/api/v1", tags=["payments"])


@router.post("/payments", response_model=PaymentResponse)
def create_payment(
    payload: PaymentRequest,
    device_auth: DeviceAuthInfo = Depends(require_device),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> PaymentResponse:
    """Charge the member balance and append one online payment ledger row."""
    return PaymentService(session).process_payment(session, device_auth, payload)


@router.post("/balance-check", response_model=BalanceCheckResponse)
def balance_check(
    payload: BalanceCheckRequest,
    request: Request,
    device_auth: DeviceAuthInfo = Depends(require_device),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> BalanceCheckResponse:
    """Verify a card PIN and return the current balance without a ledger debit."""
    ip = request.client.host if request.client else None
    return PaymentService(session).process_balance_check(
        session, device_auth, payload, ip=ip
    )


@router.get("/transactions/{txn_uuid}", response_model=TransactionStatusResponse)
def get_transaction(
    txn_uuid: str,
    device_auth: DeviceAuthInfo = Depends(require_device),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> TransactionStatusResponse:
    """Return transaction status only to the device that created it."""
    txn = session.scalar(select(Transaction).where(Transaction.txn_uuid == txn_uuid))
    if txn is None or txn.device_id != device_auth.id:
        raise DomainError(
            code="VALIDATION_ERROR",
            status_code=404,
            details={"detail": "Transaksi tidak ditemukan"},
        )
    return TransactionStatusResponse(
        txn_uuid=txn.txn_uuid,
        type=txn.type,
        direction=txn.direction,
        amount=txn.amount,
        status=txn.status,
        balance_before=txn.balance_before,
        balance_after=txn.balance_after,
        occurred_at_utc=_iso_utc(txn.occurred_at),
        reject_reason=txn.reject_reason,
    )
