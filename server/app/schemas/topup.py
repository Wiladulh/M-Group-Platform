"""Cashier top-up request and response schemas."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt

Uid = Annotated[str, Field(pattern=r"^(?:[0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})$")]
Pin4 = Annotated[str, Field(pattern=r"^[0-9]{4}$")]
Pin6 = Annotated[str, Field(pattern=r"^[0-9]{6}$")]


class TopupRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    txn_uuid: str = Field(min_length=1, max_length=64)
    uid: Uid
    amount: StrictInt = Field(gt=0)
    operator_no: StrictInt = Field(gt=0)
    operator_pin: Pin6
    pin: Pin4
    ts: StrictInt


class TopupResponse(BaseModel):
    txn_uuid: str
    member_code: str
    full_name: str
    amount: int
    balance_before: int
    balance_after: int
    status: str
    occurred_at_utc: str
    operator_code: int
    operator_name: str
    device_id: str
