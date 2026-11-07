"""Versioned Pydantic models for the bidirectional device WebSocket protocol."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MessageType = Literal[
    "hello", "hello_ok", "ping", "pong", "ack", "status",
    "bind.start", "bind.card_scanned", "bind.pin_submitted", "bind.error",
    "bind.done", "bind.cancel", "catalog.changed", "cache.invalidate",
    "cache.update", "card.status_changed", "config.changed", "force_disconnect",
]


class EnvelopeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    id: str
    type: MessageType
    ts: int
    data: dict = Field(default_factory=dict)

    @classmethod
    def build(cls, message_type: MessageType, data: dict | None = None, message_id: str | None = None):
        from datetime import UTC, datetime
        from uuid import uuid4

        return cls(id=message_id or str(uuid4()), type=message_type,
                   ts=int(datetime.now(UTC).timestamp()), data=data or {})


class HelloData(BaseModel):
    device_id: str
    token: str
    fw_version: str
    mode: str | None = None


class HelloOkData(BaseModel):
    device_id: str
    server_time_utc: str
    ping_interval_s: int = 10
    pong_timeout_s: int = 25
    idle_disconnect_s: int = 30


class PingData(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PongData(BaseModel):
    server_time_utc: str


class AckData(BaseModel):
    id: str


class StatusData(BaseModel):
    state: Literal["idle", "busy"]


class CatalogChangedData(BaseModel):
    version: int


class CacheInvalidateData(BaseModel):
    uid_list: list[str] | None = None
    all: bool = False


class CacheUpdateData(BaseModel):
    uid: str
    balance_snapshot: int
    offline_allowance: int
    card_status: str


class CardStatusChangedData(BaseModel):
    uid: str
    status: str


class ConfigChangedData(BaseModel):
    keys: list[str]


class ForceDisconnectData(BaseModel):
    reason: str
