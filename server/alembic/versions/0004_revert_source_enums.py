"""Restore top-up source enums to the authoritative Section 5 values.

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_MAP = "_0004_source_revert_map"


def upgrade() -> None:
    # Preserve exactly which rows are remapped so downgrade never rewrites
    # genuine ADMIN ledger rows or pre-existing WEBUI top-up requests.
    op.create_table(
        _MAP,
        sa.Column("table_name", sa.String(32), nullable=False),
        sa.Column("row_id", sa.Integer(), nullable=False),
        sa.Column("old_source", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("table_name", "row_id"),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    bind.execute(
        sa.text(
            f"INSERT INTO {_MAP} (table_name, row_id, old_source) "
            "SELECT 'transactions', id, source FROM transactions WHERE source = 'CASHIER'"
        )
    )
    bind.execute(
        sa.text(
            f"INSERT INTO {_MAP} (table_name, row_id, old_source) "
            "SELECT 'topup_requests', id, source FROM topup_requests WHERE source = 'ADMIN'"
        )
    )
    bind.execute(sa.text("UPDATE transactions SET source = 'ADMIN' WHERE source = 'CASHIER'"))
    bind.execute(sa.text("UPDATE topup_requests SET source = 'WEBUI' WHERE source = 'ADMIN'"))

    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("ck_transactions_source", type_="check")
        batch.create_check_constraint(
            "ck_transactions_source",
            "source IN ('ONLINE', 'OFFLINE_SYNC', 'ADMIN')",
        )
    with op.batch_alter_table("topup_requests") as batch:
        batch.drop_constraint("ck_topup_requests_source", type_="check")
        batch.create_check_constraint(
            "ck_topup_requests_source",
            "source IN ('WEBUI', 'CASHIER')",
        )


def downgrade() -> None:
    # Widen constraints before restoring only rows recorded by upgrade().
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("ck_transactions_source", type_="check")
        batch.create_check_constraint(
            "ck_transactions_source",
            "source IN ('ONLINE', 'OFFLINE_SYNC', 'ADMIN', 'CASHIER')",
        )
    with op.batch_alter_table("topup_requests") as batch:
        batch.drop_constraint("ck_topup_requests_source", type_="check")
        batch.create_check_constraint(
            "ck_topup_requests_source",
            "source IN ('WEBUI', 'CASHIER', 'ADMIN')",
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"UPDATE transactions SET source = 'CASHIER' WHERE id IN "
            f"(SELECT row_id FROM {_MAP} WHERE table_name = 'transactions' "
            "AND old_source = 'CASHIER')"
        )
    )
    bind.execute(
        sa.text(
            f"UPDATE topup_requests SET source = 'ADMIN' WHERE id IN "
            f"(SELECT row_id FROM {_MAP} WHERE table_name = 'topup_requests' "
            "AND old_source = 'ADMIN')"
        )
    )
    op.drop_table(_MAP)
