"""Cashier payment and balance-check API schemas."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Uid = Annotated[str, Field(pattern=r"^(?:[0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})$")]
Pin = Annotated[str, Field(pattern=r"^[0-9]{4}$")]


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    txn_uuid: str = Field(min_length=1, max_length=64)
    uid: Uid
    amount: int = Field(gt=0)
    ts: int
    pin: Pin


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    txn_uuid: str
    member_code: str
    full_name: str
    amount: int
    balance_before: int
    balance_after: int
    status: str
    occurred_at_utc: str


class BalanceCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: Uid
    pin: Pin
    ts: int


class BalanceCheckResponse(BaseModel):
    member_code: str
    full_name: str
    balance: int
    as_of_utc: str


class TransactionStatusResponse(BaseModel):
    txn_uuid: str
    type: str
    direction: str
    amount: int
    status: str
    balance_before: int
    balance_after: int
    occurred_at_utc: str
    reject_reason: str | None = None
