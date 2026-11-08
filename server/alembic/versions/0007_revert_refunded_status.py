"""Restore the specification-defined transaction status set after revision 0006.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0006 may have persisted this non-spec status on original payments.
    op.execute(
        "UPDATE transactions SET status='DISPENSE_FAILED' WHERE status='REFUNDED'"
    )
    with op.batch_alter_table("transactions", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_transactions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_transactions_status",
            "status IN ('COMPLETED', 'PENDING_DISPENSE', 'DISPENSE_FAILED', "
            "'REVERSED', 'REJECTED')",
        )


def downgrade() -> None:
    # Data remains DISPENSE_FAILED, which is valid under both constraints.
    with op.batch_alter_table("transactions", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_transactions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_transactions_status",
            "status IN ('COMPLETED', 'PENDING_DISPENSE', 'DISPENSE_FAILED', "
            "'REVERSED', 'REJECTED', 'REFUNDED')",
        )
