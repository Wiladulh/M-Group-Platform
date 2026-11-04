"""Initial complete database schema.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
    ]


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("username", name="uq_admin_users_username"),
    )
    op.create_table(
        "members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_code", sa.String(9), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("nik_enc", sa.Text(), nullable=False),
        sa.Column("nik_idx", sa.String(64), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("member_code", name="uq_members_member_code"),
        sa.UniqueConstraint("nik_idx", name="uq_members_nik_idx"),
        sa.CheckConstraint("balance >= 0", name="ck_members_balance_nonnegative"),
        sa.CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name="ck_members_status"),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(16), nullable=False, unique=True),
        sa.Column("hw_mac", sa.String(32)),
        sa.Column("reported_mode", sa.String(16)),
        sa.Column("last_heartbeat_json", sa.Text()),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("location", sa.String(200)),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_ip", sa.String(45)),
        sa.Column("fw_version", sa.String(40)),
        sa.Column("ws_connected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("slot_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("config_json", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("type IN ('cashier', 'vending')", name="ck_devices_type"),
        sa.CheckConstraint("reported_mode IS NULL OR reported_mode IN ('manual', 'scanner', 'vending')", name="ck_devices_reported_mode"),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_devices_status"),
        sa.CheckConstraint("slot_count BETWEEN 0 AND 16", name="ck_devices_slot_count"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(20), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(500)),
        sa.Column("image_hash", sa.String(8)),
        sa.Column("image_sha256", sa.String(64)),
        sa.Column("image_size", sa.Integer()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
        sa.CheckConstraint("price >= 0", name="ck_products_price"),
        sa.CheckConstraint("image_size IS NULL OR image_size >= 0", name="ck_products_image_size"),
    )
    op.create_table(
        "operators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_no", sa.Integer(), nullable=False),
        sa.Column("nama", sa.String(160), nullable=False),
        sa.Column("operator_pin_hash", sa.String(255), nullable=False),
        sa.Column("pin_fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("operator_no", name="uq_operators_operator_no"),
        sa.CheckConstraint("operator_no >= 1", name="ck_operators_operator_no"),
        sa.CheckConstraint("pin_fail_count >= 0", name="ck_operators_pin_fail_count"),
    )
    op.create_table(
        "catalog_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint("version >= 0", name="ck_catalog_meta_version"),
        sa.CheckConstraint("id = 1", name="ck_catalog_meta_singleton"),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(45)),
        sa.Column("user_agent", sa.Text()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_hash", name="uq_admin_sessions_session_hash"),
    )
    op.create_table(
        "cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("uid", sa.String(32), nullable=False),
        sa.Column("pin_hash", sa.Text(), nullable=False),
        sa.Column("offline_verifier", sa.Text()),
        sa.Column("offline_salt", sa.String(128)),
        sa.Column("pin_fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("bound_at", sa.DateTime(timezone=True)),
        sa.Column("bound_by_device_id", sa.Integer(), sa.ForeignKey("devices.id")),
        sa.Column("deactivated_reason", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("uid", name="uq_cards_uid"),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'LOCKED', 'REPLACED')", name="ck_cards_status"),
        sa.CheckConstraint("pin_fail_count >= 0", name="ck_cards_pin_fail_count"),
    )
    op.create_table(
        "device_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("event", sa.String(24), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_s", sa.Integer()),
        sa.Column("detail", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("event IN ('ONLINE', 'OFFLINE', 'REBOOT', 'WIFI_RECONNECT')", name="ck_device_events_event"),
        sa.CheckConstraint("duration_s IS NULL OR duration_s >= 0", name="ck_device_events_duration"),
    )
    op.create_table(
        "vending_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("slot_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id")),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("servo_type", sa.String(16), nullable=False, server_default="positional"),
        sa.Column("home_deg", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dispense_deg", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("hold_ms", sa.Integer(), nullable=False, server_default="700"),
        sa.Column("run_ms", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.UniqueConstraint("device_id", "slot_no", name="uq_vending_slots_device_slot"),
        sa.CheckConstraint("slot_no BETWEEN 1 AND 16", name="ck_vending_slots_slot_no"),
        sa.CheckConstraint("stock >= 0 AND capacity >= 0 AND stock <= capacity", name="ck_vending_slots_stock_capacity"),
        sa.CheckConstraint("servo_type IN ('positional', 'continuous')", name="ck_vending_slots_servo_type"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("txn_uuid", sa.String(36), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("cards.id")),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id")),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("balance_before", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reject_reason", sa.String(80)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("items_json", sa.Text()),
        sa.Column("ref_txn_id", sa.Integer(), sa.ForeignKey("transactions.id")),
        sa.Column("note", sa.Text()),
        sa.Column("performed_by_type", sa.String(16), nullable=False),
        sa.Column("performed_by_id", sa.String(64)),
        sa.Column("card_inactive_at_sync", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.UniqueConstraint("txn_uuid", name="uq_transactions_txn_uuid"),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.CheckConstraint("direction IN ('DEBIT', 'CREDIT')", name="ck_transactions_direction"),
        sa.CheckConstraint("type IN ('PAYMENT', 'TOPUP', 'REFUND', 'ADJUSTMENT')", name="ck_transactions_type"),
        sa.CheckConstraint("status IN ('COMPLETED', 'PENDING_DISPENSE', 'DISPENSE_FAILED', 'REVERSED', 'REJECTED')", name="ck_transactions_status"),
        sa.CheckConstraint("source IN ('ONLINE', 'OFFLINE_SYNC', 'ADMIN')", name="ck_transactions_source"),
        sa.CheckConstraint("performed_by_type IN ('ADMIN', 'OPERATOR', 'DEVICE', 'SYSTEM')", name="ck_transactions_performed_by_type"),
    )
    op.create_table(
        "offline_allowances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("member_id", "device_id", name="uq_offline_allowances_member_device"),
        sa.CheckConstraint("amount >= 0", name="ck_offline_allowances_amount"),
        sa.CheckConstraint("version >= 0", name="ck_offline_allowances_version"),
    )
    op.create_table(
        "shortfall_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("txn_uuid", sa.String(36), sa.ForeignKey("transactions.txn_uuid"), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("admin_users.id")),
        sa.Column("resolution_note", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("txn_uuid", name="uq_shortfall_records_txn_uuid"),
        sa.CheckConstraint("amount > 0", name="ck_shortfall_records_amount_positive"),
        sa.CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_shortfall_records_status"),
    )
    op.create_table(
        "pending_sync_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("batch_uuid", sa.String(36), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Integer(), nullable=False),
        sa.Column("rejected", sa.Integer(), nullable=False),
        sa.Column("detail_json", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("device_id", "batch_uuid", name="uq_pending_sync_device_batch"),
        sa.CheckConstraint("total >= 0 AND accepted >= 0 AND rejected >= 0", name="ck_pending_sync_counts"),
    )
    op.create_table(
        "card_bind_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_uuid", sa.String(36), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("uid_scanned", sa.String(32)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_admin_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=False),
        sa.Column("failure_reason", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("session_uuid", name="uq_card_bind_sessions_session_uuid"),
        sa.CheckConstraint("mode IN ('NEW_CARD', 'REPLACE_CARD', 'PIN_ONLY')", name="ck_card_bind_sessions_mode"),
        sa.CheckConstraint("state IN ('WAITING_DEVICE', 'WAITING_CARD', 'WAITING_PIN', 'CONFIRM_PIN', 'DONE', 'FAILED', 'EXPIRED', 'CANCELLED')", name="ck_card_bind_sessions_state"),
    )
    op.create_table(
        "operator_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id"), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("operator_id", "device_id", name="uq_operator_devices_operator_device"),
    )
    op.create_table(
        "topup_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_uuid", sa.String(36), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="COMPLETED"),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id")),
        sa.Column("processed_by_type", sa.String(16), nullable=False),
        sa.Column("processed_by_id", sa.String(64), nullable=False),
        sa.Column("txn_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("reversal_txn_id", sa.Integer(), sa.ForeignKey("transactions.id")),
        sa.Column("reverse_reason", sa.Text()),
        sa.Column("note", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("request_uuid", name="uq_topup_requests_request_uuid"),
        sa.UniqueConstraint("txn_id", name="uq_topup_requests_txn_id"),
        sa.CheckConstraint("amount > 0", name="ck_topup_requests_amount_positive"),
        sa.CheckConstraint("status IN ('COMPLETED', 'REVERSED')", name="ck_topup_requests_status"),
        sa.CheckConstraint("source IN ('WEBUI', 'CASHIER')", name="ck_topup_requests_source"),
        sa.CheckConstraint("processed_by_type IN ('ADMIN', 'OPERATOR')", name="ck_topup_requests_processed_by_type"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text()),
        sa.Column("ip", sa.String(45)),
        *_timestamps(),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("key", name="uq_settings_key"),
    )

    op.create_index("ix_transactions_member_occurred_at", "transactions", ["member_id", "occurred_at"])
    op.create_index("ix_transactions_device_occurred_at", "transactions", ["device_id", "occurred_at"])
    op.create_index("ix_cards_uid", "cards", ["uid"])
    op.create_index("ix_members_nik_idx", "members", ["nik_idx"])
    op.create_index("ix_topup_requests_member_created_at", "topup_requests", ["member_id", "created_at"])
    op.create_index("ix_admin_sessions_session_hash", "admin_sessions", ["session_hash"])
    op.create_index(
        "uq_cards_one_active_or_locked_per_member",
        "cards",
        ["member_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('ACTIVE', 'LOCKED')"),
    )


def downgrade() -> None:
    op.drop_index("uq_cards_one_active_or_locked_per_member", table_name="cards")
    op.drop_index("ix_admin_sessions_session_hash", table_name="admin_sessions")
    op.drop_index("ix_topup_requests_member_created_at", table_name="topup_requests")
    op.drop_index("ix_members_nik_idx", table_name="members")
    op.drop_index("ix_cards_uid", table_name="cards")
    op.drop_index("ix_transactions_device_occurred_at", table_name="transactions")
    op.drop_index("ix_transactions_member_occurred_at", table_name="transactions")

    op.drop_table("settings")
    op.drop_table("audit_logs")
    op.drop_table("topup_requests")
    op.drop_table("operator_devices")
    op.drop_table("card_bind_sessions")
    op.drop_table("pending_sync_log")
    op.drop_table("shortfall_records")
    op.drop_table("offline_allowances")
    op.drop_table("transactions")
    op.drop_table("vending_slots")
    op.drop_table("device_events")
    op.drop_table("cards")
    op.drop_table("admin_sessions")
    op.drop_table("catalog_meta")
    op.drop_table("operators")
    op.drop_table("products")
    op.drop_table("devices")
    op.drop_table("members")
    op.drop_table("admin_users")
