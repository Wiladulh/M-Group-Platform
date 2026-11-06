"""Restore top-up source enums to the authoritative Section 5 values.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _remap(table: str, old_source: str, new_source: str) -> None:
    op.get_bind().execute(
        sa.text(f"UPDATE {table} SET source = :new WHERE source = :old"),
        {"new": new_source, "old": old_source},
    )


def upgrade() -> None:
    # SQLite requires a full table rebuild to replace CHECK constraints.
    _remap("transactions", "CASHIER", "ADMIN")
    _remap("topup_requests", "ADMIN", "WEBUI")

    with op.batch_alter_table("transactions", recreate="always") as batch:
        batch.drop_constraint("ck_transactions_source", type_="check")
        batch.create_check_constraint(
            "ck_transactions_source",
            "source IN ('ONLINE', 'OFFLINE_SYNC', 'ADMIN')",
        )
    with op.batch_alter_table("topup_requests", recreate="always") as batch:
        batch.drop_constraint("ck_topup_requests_source", type_="check")
        batch.create_check_constraint(
            "ck_topup_requests_source",
            "source IN ('WEBUI', 'CASHIER')",
        )


def downgrade() -> None:
    # Lossy by design: see docs/ASSUMPTIONS.md before downgrading production.
    with op.batch_alter_table("transactions", recreate="always") as batch:
        batch.drop_constraint("ck_transactions_source", type_="check")
        batch.create_check_constraint(
            "ck_transactions_source",
            "source IN ('ONLINE', 'OFFLINE_SYNC', 'ADMIN', 'CASHIER')",
        )
    with op.batch_alter_table("topup_requests", recreate="always") as batch:
        batch.drop_constraint("ck_topup_requests_source", type_="check")
        batch.create_check_constraint(
            "ck_topup_requests_source",
            "source IN ('WEBUI', 'CASHIER', 'ADMIN')",
        )

    _remap("transactions", "ADMIN", "CASHIER")
    _remap("topup_requests", "WEBUI", "ADMIN")
