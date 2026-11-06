"""Allow cashier-origin TOPUP ledger rows.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("ck_transactions_source", type_="check")
        batch.create_check_constraint(
            "ck_transactions_source",
            "source IN ('ONLINE', 'OFFLINE_SYNC', 'ADMIN', 'CASHIER')",
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("ck_transactions_source", type_="check")
        batch.create_check_constraint(
            "ck_transactions_source",
            "source IN ('ONLINE', 'OFFLINE_SYNC', 'ADMIN')",
        )
