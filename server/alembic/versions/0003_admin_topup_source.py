"""Allow admin-origin top-up request rows.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("topup_requests") as batch:
        batch.drop_constraint("ck_topup_requests_source", type_="check")
        batch.create_check_constraint(
            "ck_topup_requests_source",
            "source IN ('WEBUI', 'CASHIER', 'ADMIN')",
        )


def downgrade() -> None:
    with op.batch_alter_table("topup_requests") as batch:
        batch.drop_constraint("ck_topup_requests_source", type_="check")
        batch.create_check_constraint(
            "ck_topup_requests_source",
            "source IN ('WEBUI', 'CASHIER')",
        )
