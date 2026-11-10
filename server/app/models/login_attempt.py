"""Admin login attempt tracking for rate limiting."""

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LoginAttempt(TimestampMixin, Base):
    """Record of a single admin login attempt (success or failure)."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index(
            "ix_login_attempts_lookup",
            "ip",
            "username",
            "success",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
