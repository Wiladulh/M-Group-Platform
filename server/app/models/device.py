"""Registered devices and device lifecycle events."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Device(TimestampMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("type IN ('cashier', 'vending')", name="ck_devices_type"),
        CheckConstraint("reported_mode IS NULL OR reported_mode IN ('manual', 'scanner', 'vending')", name="ck_devices_reported_mode"),
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_devices_status"),
        CheckConstraint("slot_count BETWEEN 0 AND 16", name="ck_devices_slot_count"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    hw_mac: Mapped[str | None] = mapped_column(String(32))
    reported_mode: Mapped[str | None] = mapped_column(String(16))
    last_heartbeat_json: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ip: Mapped[str | None] = mapped_column(String(45))
    fw_version: Mapped[str | None] = mapped_column(String(40))
    ws_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    slot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    config_json: Mapped[str | None] = mapped_column(Text)


class DeviceEvent(TimestampMixin, Base):
    __tablename__ = "device_events"
    __table_args__ = (
        CheckConstraint("event IN ('ONLINE', 'OFFLINE', 'REBOOT', 'WIFI_RECONNECT')", name="ck_device_events_event"),
        CheckConstraint("duration_s IS NULL OR duration_s >= 0", name="ck_device_events_duration"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    event: Mapped[str] = mapped_column(String(24), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
