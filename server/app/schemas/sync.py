"""Offline synchronization and member-cache response schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SyncItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    txn_uuid: str = Field(min_length=1, max_length=36)
    uid: str = Field(min_length=1, max_length=32)
    slot_no: int | None = Field(default=None, ge=1, le=16)
    product_id: int | None = Field(default=None, ge=1)
    manual_amount: int | None = Field(default=None, gt=0)
    price: int = Field(gt=0)
    offline_ts: int = Field(ge=0)
    ts_untrusted: int | None = None
    dispense_result: Literal["ok", "failed", "unknown"] | None = None
    pin_fail_events: int = Field(default=0, ge=0)

    @field_validator("uid")
    @classmethod
    def normalize_uid(cls, value: str) -> str:
        return value.strip().upper()


class SyncBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_uuid: str = Field(min_length=1, max_length=36)
    items: list[SyncItem] = Field(max_length=50)


class SyncItemResult(BaseModel):
    txn_uuid: str
    status: Literal["ACCEPTED", "DUPLICATE", "REJECTED"]
    reason: str | None = None
    balance_after: int | None = None
    shortfall_id: int | None = None


class CacheEntryDelta(BaseModel):
    uid: str
    member_code: str
    name: str
    balance_snapshot: int
    snapshot_ts: str
    offline_allowance: int
    card_status: str
    entry_version: int


class SyncResponse(BaseModel):
    batch_uuid: str
    total: int
    accepted: int
    rejected: int
    results: list[SyncItemResult]
    cache_version: int
    member_cache_delta: list[CacheEntryDelta]


class MemberCacheResponse(BaseModel):
    cache_version: int
    entries: list[CacheEntryDelta]
