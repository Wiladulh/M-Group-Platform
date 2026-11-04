"""Member accounts and replaceable NFC cards."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Member(TimestampMixin, Base):
    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("member_code", name="uq_members_member_code"),
        UniqueConstraint("nik_idx", name="uq_members_nik_idx"),
        CheckConstraint("balance >= 0", name="ck_members_balance_nonnegative"),
        CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name="ck_members_status"),
        Index("ix_members_nik_idx", "nik_idx"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_code: Mapped[str] = mapped_column(String(9), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    nik_enc: Mapped[str] = mapped_column(Text, nullable=False)
    nik_idx: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    notes: Mapped[str | None] = mapped_column(Text)


class Card(TimestampMixin, Base):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("uid", name="uq_cards_uid"),
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'LOCKED', 'REPLACED')",
            name="ck_cards_status",
        ),
        CheckConstraint("pin_fail_count >= 0", name="ck_cards_pin_fail_count"),
        Index("ix_cards_uid", "uid"),
        Index(
            "uq_cards_one_active_or_locked_per_member",
            "member_id",
            unique=True,
            sqlite_where=text("status IN ('ACTIVE', 'LOCKED')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    uid: Mapped[str] = mapped_column(String(32), nullable=False)
    pin_hash: Mapped[str] = mapped_column(Text, nullable=False)
    offline_verifier: Mapped[str | None] = mapped_column(Text)
    offline_salt: Mapped[str | None] = mapped_column(String(128))
    pin_fail_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bound_by_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    deactivated_reason: Mapped[str | None] = mapped_column(Text)
