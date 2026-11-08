"""Allow final REFUNDED status for automatically refunded dispense transactions.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_transactions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_transactions_status",
            "status IN ('COMPLETED', 'PENDING_DISPENSE', 'DISPENSE_FAILED', "
            "'REFUNDED', 'REVERSED', 'REJECTED')",
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_transactions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_transactions_status",
            "status IN ('COMPLETED', 'PENDING_DISPENSE', 'DISPENSE_FAILED', "
            "'REVERSED', 'REJECTED')",
        )
