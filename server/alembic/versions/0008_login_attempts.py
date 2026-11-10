"""Add login_attempts table for rate limiting.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create login_attempts table with composite lookup index."""
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index(
        "ix_login_attempts_lookup",
        "login_attempts",
        ["ip", "username", "success", "created_at"],
    )


def downgrade() -> None:
    """Drop login_attempts table."""
    op.drop_index("ix_login_attempts_lookup", table_name="login_attempts")
    op.drop_table("login_attempts")
