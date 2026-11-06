"""Financial ledger, offline allowance, sync, shortfall, and top-up records."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("txn_uuid", name="uq_transactions_txn_uuid"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("direction IN ('DEBIT', 'CREDIT')", name="ck_transactions_direction"),
        CheckConstraint(
            "type IN ('PAYMENT', 'TOPUP', 'REFUND', 'ADJUSTMENT')",
            name="ck_transactions_type",
        ),
        CheckConstraint(
            "status IN ('COMPLETED', 'PENDING_DISPENSE', 'DISPENSE_FAILED', 'REVERSED', 'REJECTED')",
            name="ck_transactions_status",
        ),
        CheckConstraint(
            "source IN ('ONLINE', 'OFFLINE_SYNC', 'ADMIN', 'CASHIER')",
            name="ck_transactions_source",
        ),
        CheckConstraint(
            "performed_by_type IN ('ADMIN', 'OPERATOR', 'DEVICE', 'SYSTEM')",
            name="ck_transactions_performed_by_type",
        ),
        Index("ix_transactions_member_occurred_at", "member_id", "occurred_at"),
        Index("ix_transactions_device_occurred_at", "device_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    txn_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    balance_before: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    items_json: Mapped[str | None] = mapped_column(Text)
    ref_txn_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    note: Mapped[str | None] = mapped_column(Text)
    performed_by_type: Mapped[str] = mapped_column(String(16), nullable=False)
    performed_by_id: Mapped[str | None] = mapped_column(String(64))
    card_inactive_at_sync: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="0"
    )


class OfflineAllowance(TimestampMixin, Base):
    __tablename__ = "offline_allowances"
    __table_args__ = (
        UniqueConstraint("member_id", "device_id", name="uq_offline_allowances_member_device"),
        CheckConstraint("amount >= 0", name="ck_offline_allowances_amount"),
        CheckConstraint("version >= 0", name="ck_offline_allowances_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class ShortfallRecord(TimestampMixin, Base):
    __tablename__ = "shortfall_records"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_shortfall_records_amount_positive"),
        CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_shortfall_records_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    txn_uuid: Mapped[str] = mapped_column(
        ForeignKey("transactions.txn_uuid"), nullable=False, unique=True
    )
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OPEN", server_default="OPEN"
    )
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class PendingSyncLog(TimestampMixin, Base):
    __tablename__ = "pending_sync_log"
    __table_args__ = (
        UniqueConstraint("device_id", "batch_uuid", name="uq_pending_sync_device_batch"),
        CheckConstraint(
            "total >= 0 AND accepted >= 0 AND rejected >= 0",
            name="ck_pending_sync_counts",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    batch_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False)
    detail_json: Mapped[str | None] = mapped_column(Text)


class TopUpRequest(TimestampMixin, Base):
    __tablename__ = "topup_requests"
    __table_args__ = (
        UniqueConstraint("request_uuid", name="uq_topup_requests_request_uuid"),
        UniqueConstraint("txn_id", name="uq_topup_requests_txn_id"),
        CheckConstraint("amount > 0", name="ck_topup_requests_amount_positive"),
        CheckConstraint("status IN ('COMPLETED', 'REVERSED')", name="ck_topup_requests_status"),
        CheckConstraint("source IN ('WEBUI', 'CASHIER')", name="ck_topup_requests_source"),
        CheckConstraint(
            "processed_by_type IN ('ADMIN', 'OPERATOR')",
            name="ck_topup_requests_processed_by_type",
        ),
        Index("ix_topup_requests_member_created_at", "member_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="COMPLETED", server_default="COMPLETED"
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    processed_by_type: Mapped[str] = mapped_column(String(16), nullable=False)
    processed_by_id: Mapped[str] = mapped_column(String(64), nullable=False)
    txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    reversal_txn_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    reverse_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
