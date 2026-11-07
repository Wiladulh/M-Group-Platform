"""Remote card and member PIN binding sessions."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CardBindSession(TimestampMixin, Base):
    __tablename__ = "card_bind_sessions"
    __table_args__ = (
        UniqueConstraint("session_uuid", name="uq_card_bind_sessions_session_uuid"),
        CheckConstraint(
            "mode IN ('NEW_CARD', 'REPLACE_CARD', 'PIN_ONLY')",
            name="ck_card_bind_sessions_mode",
        ),
        CheckConstraint(
            "state IN ('WAITING_DEVICE', 'WAITING_CARD', 'WAITING_PIN', 'CONFIRM_PIN', 'DONE', 'FAILED', 'EXPIRED', 'CANCELLED')",
            name="ck_card_bind_sessions_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    uid_scanned: Mapped[str | None] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_admin_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    pin_attempts: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    pin_candidate_hash: Mapped[str | None] = mapped_column(String(64))
