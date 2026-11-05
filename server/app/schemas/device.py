"""Device-facing API schemas."""

from pydantic import BaseModel, ConfigDict, Field


class DeviceConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    name: str
    type: str
    mode: str | None = None
    slot_count: int | None = None
    offline_enabled: bool
    offline_txn_max: int
    offline_card_cap: int
    offline_hold_mode: str
    catalog_version: int | None = None
    server_time_utc: str
    device_config_overrides: dict = Field(default_factory=dict)
