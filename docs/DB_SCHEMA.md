# Dokumentasi Skema Database

Skema ini mengikuti Section 5 spesifikasi M-Group Platform v1.3. Seluruh nominal uang disimpan sebagai INTEGER Rupiah. Timestamp menggunakan DateTime(timezone=True) dan merepresentasikan UTC. SQLite tidak memiliki tipe timestamp ber-timezone native; aplikasi harus menulis dan menafsirkan nilai sebagai UTC.

## Ringkasan

- 19 tabel dalam satu migration awal, Alembic revision 0001.
- Seluruh tabel memiliki id INTEGER primary key, created_at dan updated_at UTC.
- Enum/status disimpan sebagai String dengan CHECK constraint SQLite.
- Tidak menggunakan relationship() ORM; navigasi lintas tabel memakai FK dan explicit joins.
- Payload JSON disimpan sebagai TEXT.

## Identity — admin, member, kartu

### admin_users
Akun tunggal pemilik WebUI. Kolom: id, username VARCHAR(80), display_name VARCHAR(160), password_hash TEXT, must_change_password BOOLEAN, last_login_at DATETIME nullable, created_at, updated_at. Constraint: username UNIQUE.

### admin_sessions
Session cookie tersimpan sebagai hash. Kolom: id, user_id FK admin_users.id, session_hash VARCHAR(64), created_at, updated_at, last_seen_at, expires_at, ip VARCHAR(45) nullable, user_agent TEXT nullable, revoked_at nullable. Constraint: session_hash UNIQUE. Index eksplisit: ix_admin_sessions_session_hash.

### members
Identitas dan saldo member. Kolom: id, member_code VARCHAR(9), full_name VARCHAR(160), nik_enc TEXT, nik_idx VARCHAR(64), phone VARCHAR(32) nullable, balance INTEGER, status VARCHAR(16), notes TEXT nullable, timestamps. Constraint: member_code UNIQUE, nik_idx UNIQUE, CHECK(balance >= 0), status ACTIVE|SUSPENDED. Index eksplisit: ix_members_nik_idx.

### cards
Kartu NFC yang dapat diganti tanpa memindahkan saldo. Kolom: id, member_id FK members.id, uid VARCHAR(32), pin_hash TEXT, offline_verifier TEXT nullable, offline_salt VARCHAR(128) nullable, pin_fail_count INTEGER, status VARCHAR(16), bound_at nullable, bound_by_device_id FK devices.id nullable, deactivated_reason TEXT nullable, timestamps. Constraint: uid UNIQUE; status ACTIVE|INACTIVE|LOCKED|REPLACED; pin_fail_count >= 0. Index: ix_cards_uid dan partial unique index uq_cards_one_active_or_locked_per_member pada member_id dengan predicate status IN ('ACTIVE', 'LOCKED').

### card_bind_sessions
Alur binding kartu/PIN. Kolom: id, session_uuid VARCHAR(36), member_id FK members.id, device_id FK devices.id, mode VARCHAR(16), state VARCHAR(24), uid_scanned VARCHAR(32) nullable, expires_at, created_by_admin_id FK admin_users.id, failure_reason TEXT nullable, timestamps. Constraint: session_uuid UNIQUE; mode NEW_CARD|REPLACE_CARD|PIN_ONLY; state WAITING_DEVICE|WAITING_CARD|WAITING_PIN|CONFIRM_PIN|DONE|FAILED|EXPIRED|CANCELLED.

## Device — unit dan katalog

### devices
Registrasi Cashier/Vending. Kolom: id, device_id VARCHAR(16), hw_mac VARCHAR(32) nullable, reported_mode VARCHAR(16) nullable, last_heartbeat_json TEXT nullable, name VARCHAR(120), type VARCHAR(16), location VARCHAR(200) nullable, token_hash VARCHAR(64), status VARCHAR(16), last_seen_at nullable, last_ip VARCHAR(45) nullable, fw_version VARCHAR(40) nullable, ws_connected BOOLEAN, slot_count INTEGER, config_json TEXT nullable, timestamps. Constraint: device_id dan token_hash UNIQUE; type cashier|vending; reported_mode manual|scanner|vending atau NULL; status ACTIVE|REVOKED; slot_count 0..16.

### device_events
Riwayat online/offline/reboot/reconnect. Kolom: id, device_id FK devices.id, event VARCHAR(24), at DATETIME, duration_s INTEGER nullable, detail TEXT nullable, timestamps. Constraint: event ONLINE|OFFLINE|REBOOT|WIFI_RECONNECT; duration_s NULL atau >= 0.

### products
Katalog produk. Kolom: id, sku VARCHAR(20), name VARCHAR(160), description TEXT nullable, price INTEGER, image_path VARCHAR(500) nullable, image_hash VARCHAR(8) nullable, image_sha256 VARCHAR(64) nullable, image_size INTEGER nullable, is_active BOOLEAN, timestamps. Constraint: sku UNIQUE; price >= 0; image_size NULL atau >= 0.

### vending_slots
Slot dan parameter servo. Kolom: id, device_id FK devices.id, slot_no INTEGER, product_id FK products.id nullable, stock INTEGER, capacity INTEGER, servo_type VARCHAR(16), home_deg INTEGER, dispense_deg INTEGER, hold_ms INTEGER, run_ms INTEGER, timestamps. Constraint: UNIQUE(device_id, slot_no); slot_no 1..16; stock/capacity nonnegative dan stock <= capacity; servo_type positional|continuous.

### catalog_meta
Versi katalog singleton. Kolom: id, version INTEGER, timestamps. Constraint: version >= 0 dan CHECK(id = 1).

## Commerce — ledger dan top-up

### transactions
Ledger append-only. Kolom: id, txn_uuid VARCHAR(36), member_id FK members.id, card_id FK cards.id nullable, device_id FK devices.id nullable, type VARCHAR(16), amount INTEGER, direction VARCHAR(8), balance_before INTEGER, balance_after INTEGER, status VARCHAR(24), reject_reason VARCHAR(80) nullable, source VARCHAR(16), occurred_at DATETIME, items_json TEXT nullable, ref_txn_id FK transactions.id nullable, note TEXT nullable, performed_by_type VARCHAR(16), performed_by_id VARCHAR(64) nullable, card_inactive_at_sync BOOLEAN, timestamps. Constraint: txn_uuid UNIQUE; amount > 0; type PAYMENT|TOPUP|REFUND|ADJUSTMENT; direction DEBIT|CREDIT; status COMPLETED|PENDING_DISPENSE|DISPENSE_FAILED|REVERSED|REJECTED; source ONLINE|OFFLINE_SYNC|ADMIN; performed_by_type ADMIN|OPERATOR|DEVICE|SYSTEM. Index: ix_transactions_member_occurred_at dan ix_transactions_device_occurred_at.

### offline_allowances
Allowance offline per member/perangkat. Kolom: id, member_id FK members.id, device_id FK devices.id, amount INTEGER, computed_at DATETIME, version INTEGER, timestamps. Constraint: UNIQUE(member_id, device_id); amount >= 0; version >= 0.

### topup_requests
Permintaan top-up WebUI/Cashier yang ditautkan 1:1 ke ledger TOPUP. Kolom: id, request_uuid VARCHAR(36), member_id FK members.id, amount INTEGER, status VARCHAR(16), source VARCHAR(16), device_id FK devices.id nullable, processed_by_type VARCHAR(16), processed_by_id VARCHAR(64), txn_id FK transactions.id, reversal_txn_id FK transactions.id nullable, reverse_reason TEXT nullable, note TEXT nullable, timestamps. Constraint: request_uuid UNIQUE; txn_id UNIQUE; amount > 0; status COMPLETED|REVERSED; source WEBUI|CASHIER; processed_by_type ADMIN|OPERATOR. Index: ix_topup_requests_member_created_at.

### shortfall_records
Catatan kerugian offline saat sync. Kolom: id, txn_uuid FK transactions.txn_uuid, device_id FK devices.id, member_id FK members.id, amount INTEGER, occurred_at DATETIME, reason VARCHAR(120), status VARCHAR(16), resolved_by FK admin_users.id nullable, resolution_note TEXT nullable, timestamps. Constraint: txn_uuid UNIQUE; amount > 0; status OPEN|RESOLVED.

### pending_sync_log
Ringkasan batch sync. Kolom: id, device_id FK devices.id, batch_uuid VARCHAR(36), received_at DATETIME, total INTEGER, accepted INTEGER, rejected INTEGER, detail_json TEXT nullable, timestamps. Constraint: UNIQUE(device_id, batch_uuid); total, accepted, rejected >= 0.

## Safety — operator dan audit

### operators
Operator Cashier. Kolom: id, operator_no INTEGER, nama VARCHAR(160), operator_pin_hash VARCHAR(255), pin_fail_count INTEGER, locked_until nullable, is_active BOOLEAN, timestamps. Constraint: operator_no UNIQUE dan >= 1; pin_fail_count >= 0.

### operator_devices
Relasi operator dan Cashier. Kolom: id, operator_id FK operators.id, device_id FK devices.id, timestamps. Constraint: UNIQUE(operator_id, device_id).

### audit_logs
Jejak tindakan. Kolom: id, actor_type VARCHAR(16), actor_id VARCHAR(64) nullable, action VARCHAR(80), entity VARCHAR(80), entity_id VARCHAR(64) nullable, before_json TEXT nullable, after_json TEXT nullable, ip VARCHAR(45) nullable, timestamps.

### settings
Parameter sistem key-value. Kolom: id, key VARCHAR(100), value TEXT, timestamps. Constraint: key UNIQUE.

## Mermaid ER diagram

\`\`\`mermaid
erDiagram
    ADMIN_USERS ||--o{ ADMIN_SESSIONS : owns
    ADMIN_USERS ||--o{ CARD_BIND_SESSIONS : creates
    ADMIN_USERS ||--o{ SHORTFALL_RECORDS : resolves
    MEMBERS ||--o{ CARDS : holds
    MEMBERS ||--o{ TRANSACTIONS : owns
    MEMBERS ||--o{ OFFLINE_ALLOWANCES : receives
    MEMBERS ||--o{ CARD_BIND_SESSIONS : binds
    MEMBERS ||--o{ TOPUP_REQUESTS : tops_up
    MEMBERS ||--o{ SHORTFALL_RECORDS : incurs
    DEVICES ||--o{ DEVICE_EVENTS : emits
    DEVICES ||--o{ VENDING_SLOTS : contains
    DEVICES ||--o{ TRANSACTIONS : processes
    DEVICES ||--o{ OFFLINE_ALLOWANCES : grants
    DEVICES ||--o{ CARD_BIND_SESSIONS : serves
    DEVICES ||--o{ OPERATOR_DEVICES : assigned
    DEVICES ||--o{ PENDING_SYNC_LOG : syncs
    DEVICES ||--o{ TOPUP_REQUESTS : source
    DEVICES ||--o{ CARDS : binds
    PRODUCTS ||--o{ VENDING_SLOTS : stocked
    CARDS ||--o{ TRANSACTIONS : used_for
    TRANSACTIONS ||--o{ TRANSACTIONS : reverses
    TRANSACTIONS ||--o| TOPUP_REQUESTS : topup_ledger
    TRANSACTIONS ||--o| SHORTFALL_RECORDS : shortfall
    OPERATORS ||--o{ OPERATOR_DEVICES : assigned
    OPERATORS ||--o{ TOPUP_REQUESTS : processes
\`\`\`

## Indeks

Enam indeks wajib spesifikasi ditambahkan, ditambah partial unique index:
1. transactions(member_id, occurred_at)
2. transactions(device_id, occurred_at)
3. cards(uid)
4. members(nik_idx)
5. topup_requests(member_id, created_at)
6. admin_sessions(session_hash)
7. Partial UNIQUE cards(member_id) WHERE status IN ('ACTIVE', 'LOCKED').

Constraint UNIQUE lainnya juga menghasilkan indeks unik SQLite.

## Migrasi

- Upgrade: cd server && alembic upgrade head
- Downgrade penuh: cd server && alembic downgrade base
- Revision awal: 0001. Migration hanya membentuk struktur dan constraint, tanpa seed data.
