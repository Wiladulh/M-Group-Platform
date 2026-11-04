"""Cashier operators and their device assignments."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Operator(TimestampMixin, Base):
    __tablename__ = "operators"
    __table_args__ = (
        UniqueConstraint("operator_no", name="uq_operators_operator_no"),
        CheckConstraint("operator_no >= 1", name="ck_operators_operator_no"),
        CheckConstraint("pin_fail_count >= 0", name="ck_operators_pin_fail_count"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_no: Mapped[int] = mapped_column(Integer, nullable=False)
    nama: Mapped[str] = mapped_column(String(160), nullable=False)
    operator_pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    pin_fail_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )


class OperatorDevice(TimestampMixin, Base):
    __tablename__ = "operator_devices"
    __table_args__ = (
        UniqueConstraint("operator_id", "device_id", name="uq_operator_devices_operator_device"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
