"""Persist safe PIN-confirmation state for remote card binding.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "card_bind_sessions",
        sa.Column("pin_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "card_bind_sessions",
        sa.Column("pin_candidate_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("card_bind_sessions", "pin_candidate_hash")
    op.drop_column("card_bind_sessions", "pin_attempts")
