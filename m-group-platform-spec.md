# M-GROUP PLATFORM: ABSOLUTE SPECIFICATION v1.3

You are a senior engineer building this project FROM SCRATCH (no prior code or context). This document is the single source of truth.

## 0. WORKING RULES (MANDATORY)

1. Do not ask questions back. If something is not written, follow Section 17 (Decision Log). If still not covered, choose the safest and simplest option, then record it in `/docs/ASSUMPTIONS.md`.
2. No placeholders, `TODO`, `pass`, pseudo-code, or empty functions. All code must run.
3. All money is INTEGER Rupiah (no decimals, no float) across the entire system.
4. All times stored in UTC (ISO 8601) and displayed in Asia/Jakarta (UTC+7).
5. A phase is complete only when the criteria in Section 16 pass. Run tests and builds yourself; fix until green.
6. Modular code, typed (type hints / clear headers), with adequate comments and documentation in `/docs`.
7. UI language and device screen messages: Bahasa Indonesia. Code, variable names, and comments: English. Documentation: Bahasa Indonesia.
8. **GOLDEN BALANCE RULE: a member's balance MUST NEVER be negative, under any condition.** If balance is insufficient, the transaction is rejected (Section 10.4 explains remaining offline cases).
9. Canonical terms are in Section 19 (Glossary); use them consistently in code, UI, and documentation. Section 14 is the complete and binding WebUI specification: do not add menus or features beyond it.

## 1. ARCHITECTURE
- Server-centric, offline-first resilience. Server is the source of truth for balance.
- **Member UID** (`member_code`, format `MG-A00001` to `MG-Z99999`: one letter `A`-`Z` + 5 digits `00001`-`99999`; generated server-side from `members.id` (AUTOINCREMENT) n where letter = `A` + (n-1) // 99999 and number = (n-1) % 99999 + 1 zero-padded to 5 digits; capacity 2,599,974 members; never changes and never reused; if capacity exhausted, registration is rejected with `VALIDATION_ERROR`) is the primary member identity. **Card UID** (NFC HEX code) is the physical card identity linked to the Member UID. One member has exactly ONE active card at a time. Balance and transaction history belong to the MEMBER (not the card), so replacing a card does not lose balance or history.
- Card UID written as uppercase HEX without separators (e.g. `04A1B2C3`). Length 4, 7, or 10 bytes.
- Every NFC payment (Cashier and Vending) REQUIRES a 4-digit transaction PIN.
- Device-server communication: REST (catalog, images, transactions, sync) + persistent WebSocket (server-push commands, e.g. remote binding, heartbeat, cache updates).
- Three actor types: Admin (WebUI), Cashier unit (ESP32), Vending unit (ESP32).
- **Design priority: units should NEVER go offline if possible.** Offline is an emergency condition; firmware must aggressively reconnect (Section 11) and give a clear green LED signal.

## 2. DIRECTORY STRUCTURE
/server/
app/ (main.py, config.py, db.py, models/, schemas/, routers/, services/, ws/, security/, templates/, static/ (+ static/vendor/ containing local htmx, alpine, chart.js))
alembic/ , tests/ , tailwind/ , pyproject.toml , .env.example , Dockerfile , docker-compose.yml
/firmware-common/    (shared PlatformIO library: net_manager, status_led, offline_queue, member_cache, pin_verifier, protocol, provisioning, keypad, util; + native tests)
/firmware-cashier/   (PlatformIO: platformio.ini, src/, include/, README.md; uses ../firmware-common via lib_extra_dirs)
/firmware-vending/   (PlatformIO: platformio.ini, src/, include/, data/, partitions.csv, README.md; uses ../firmware-common)
/docs/               (ARCHITECTURE.md, API.md, WS_PROTOCOL.md, DB_SCHEMA.md, HARDWARE.md, SECURITY.md, ASSUMPTIONS.md, DEPLOY.md, PROGRESS.md, WEBUI.md)
/tools/              (seed_data.py, device_simulator.py, backup.sh)
README.md

## 3. TECHNOLOGY STACK (FIXED, do not change)

**Server**
- Python 3.11+, FastAPI, Uvicorn, SQLAlchemy 2.x, Alembic, Pydantic v2, SQLite WAL mode (`PRAGMA foreign_keys=ON`, `busy_timeout=5000`).
- PIN and password hashing: Argon2id (`argon2-cffi`).
- WebUI templates: Jinja2 + HTMX + Alpine.js. Styling: Tailwind CSS via Tailwind standalone CLI (no Node, no CDN; all assets local so it runs on LAN without internet). HTMX, Alpine.js, and Chart.js 4.x are vendored as local files in `static/vendor/` (committed, pinned versions).
- Images: Pillow. Export: built-in `csv` + `openpyxl` (XLSX). Test: pytest + httpx + pytest-asyncio (+ Playwright for WebUI smoke test). Lint: ruff.
- Deploy: Docker + docker-compose, plus option to run directly via `uvicorn`.

**Firmware**
- PlatformIO + Arduino framework (arduino-esp32 2.x).
- Libraries: MFRC522, U8g2 (OLED SSD1306 128x64), ArduinoJson 7, WebSockets (links2004), LittleFS, WiFiManager (provisioning portal), ESP32Servo (Vending).
- Vending: LovyanGFX + TJpg_Decoder (image display).
- Keypad written from scratch (no Keypad library) in firmware-common.
- Time: NTP (`pool.ntp.org`, fallback local server), Asia/Jakarta timezone.

## 4. SECURITY & AUTHENTICATION
### 4.1 Admin WebUI
- Login username + password (Argon2id). Session via cookie `HttpOnly`, `SameSite=Lax`, `Secure` if HTTPS. CSRF token for all POST/PUT/DELETE forms.
- Only ONE admin account: the owner and manager of the server and the only WebUI user. No roles and no staff accounts; admin can do everything (Section 14.2). The term "Operator" is reserved for the cashier officer holding a 6-digit PIN on the Cashier keypad (Section 14.10), not a WebUI account.
- Login rate limit: 5 failures per 15 minutes per IP+username, then 15-minute block.
- Session stored server-side (`admin_sessions` table): valid 24 hours since last activity (sliding: every page opened before expiry resets the count back to 0), no absolute limit; revoked on logout or password change (other sessions). **No Admin API Token**: `/admin/*` routes only accept session cookie and reject `Authorization` header.
- Admin password policy: minimum 10 characters, contains letters and numbers, not equal to username and not equal to previous password.
- Single admin account created at seed from env `ADMIN_USERNAME` and `ADMIN_PASSWORD`. Must change password on first login. Forgot password: `python -m app.cli reset-admin-password` (run on server; prompts for new password and revokes all sessions).
- Audit log for all admin actions (who, what, when, before/after).

### 4.2 Device
- Each unit is registered by admin in the WebUI (name, type `cashier|vending`, location). Server generates `device_id` (`CSH-001` for Cashier, `VND-001` for Vending; sequential, never reused, separate from hardware identity) + **Device Key** (= `device_token`, random 32 bytes; displayed ONCE; stored in DB as SHA-256 hash).
- All REST requests: header `Authorization: Bearer <device_token>` + `X-Device-Id`. WebSocket: token sent in the first `hello` message (not in URL).
- Token can be revoked/rotated from WebUI (device immediately rejected and disconnected).
- Online transaction requests include `ts` (epoch seconds); server rejects if difference > 300 seconds (`CLOCK_SKEW`). Offline sync transactions use `offline_ts` and are validated separately.
- Transport: plain HTTP/WS for closed LAN; supports `https/wss` via reverse proxy (documented in DEPLOY.md). Firmware has a `USE_TLS` option with CA pinning via file.

### 4.3 Transaction PIN
- 4 digits. Stored server-side as Argon2id(`PIN + pepper`), pepper from env `PIN_PEPPER`.
- 3 consecutive wrong PINs: card status `LOCKED` automatically. Only admin can unlock (WebUI) or reset PIN (remote binding PIN-only mode, Section 7.4).
- Weak PIN blocklist on set: `0000, 1111, ... 9999, 1234, 4321, 2580`.
- PIN is never logged, never stored plaintext on device or server, and only sent once per transaction.
- Honest note for SECURITY.md: a 4-digit PIN is weak against offline brute-force if device cache leaks. Mitigations: lockout, offline amount limit (allowance), and cache encryption.

### 4.4 Sensitive Data
- NIK is stored encrypted (Fernet, key env `DATA_KEY`) plus a blind index `HMAC-SHA256(nik, DATA_KEY)` for exact-match search. NIK is masked in UI (`3201••••••••1234`), shown in full only after admin presses "reveal" (recorded in audit log). NIK is MANDATORY and filled ONCE at registration, WITHOUT format validation (free string), unique (checked via blind index), and encrypted. KTP photo and address are not stored.

## 5. DATABASE SCHEMA (SQLite)

All tables have `id INTEGER PK`, `created_at`, `updated_at` (UTC) unless stated otherwise.

- `admin_users`: username (unique), display_name, password_hash, must_change_password, last_login_at. Only ONE row (single admin account, no role).
- `admin_sessions`: user_id FK, session_hash (SHA-256 of cookie token), created_at, last_seen_at, expires_at, ip, user_agent, revoked_at.
- `members`: member_code (unique, format `MG-A00001` to `MG-Z99999`, rule in Section 1), full_name, nik_enc, nik_idx (unique, NOT NULL — mandatory at registration), phone (nullable), **balance INTEGER with `CHECK(balance >= 0)`**, status (`ACTIVE|SUSPENDED`), notes.
- `cards`: member_id FK, uid (unique), pin_hash (Argon2id), offline_verifier + offline_salt (PBKDF2, Section 10.1), pin_fail_count, status (`ACTIVE|INACTIVE|LOCKED|REPLACED`), bound_at, bound_by_device_id, deactivated_reason. Only one `ACTIVE|LOCKED` card per member (partial unique index). UID not reused by another member unless old card is `REPLACED` and released by admin.
- `devices`: device_id (unique, `CSH-001` / `VND-001`), hw_mac (hardware identity, reported by device on `hello`; informational, not authentication), reported_mode (`manual|scanner|vending`), last_heartbeat_json (last heartbeat payload), name, type, location, token_hash, status (`ACTIVE|REVOKED`), last_seen_at, last_ip, fw_version, ws_connected (runtime), slot_count (Vending, default 5, max 16), config_json (offline_enabled, offline_txn_max, offline_card_cap, etc.; overrides global settings).
- `device_events`: device_id, event (`ONLINE|OFFLINE|REBOOT|WIFI_RECONNECT`), at, duration_s (for OFFLINE when back online), detail. Basis for uptime reports.
- `products`: sku (unique; generated by server `PRD-0001`, displayed as "ID Produk"), name, description (nullable, WebUI only), price (INTEGER), image_path, image_hash (8 hex), image_sha256, image_size, is_active (no hard delete).
- `vending_slots`: device_id FK, slot_no (1..slot_count), product_id FK (nullable), stock, capacity, servo_type (`positional|continuous`), home_deg, dispense_deg, hold_ms, run_ms. Unique (device_id, slot_no).
- `transactions` (LEDGER, append-only; only `status` column may transition per rules):
  `txn_uuid` (unique, idempotency key from device), member_id, card_id, device_id, type (`PAYMENT|TOPUP|REFUND|ADJUSTMENT`), amount (positive INTEGER), direction (`DEBIT|CREDIT`), balance_before, balance_after, status (`COMPLETED|PENDING_DISPENSE|DISPENSE_FAILED|REVERSED|REJECTED`), reject_reason (nullable), source (`ONLINE|OFFLINE_SYNC|ADMIN`), occurred_at, items_json, ref_txn_id, note, performed_by_type (`ADMIN|OPERATOR|DEVICE|SYSTEM`), performed_by_id, card_inactive_at_sync (bool). For `source=ADMIN`: `device_id` NULL and `txn_uuid` generated by server.
- `offline_allowances`: member_id, device_id, amount (INTEGER ≥ 0), computed_at, version. Unique (member_id, device_id). Offline spending cap per card per unit (Section 10.1).
- `shortfall_records`: txn_uuid, device_id, member_id, amount, occurred_at, reason, status (`OPEN|RESOLVED`), resolved_by, resolution_note. Records offline transactions REJECTED at sync because balance was insufficient (goods already dispensed = loss); member balance is NOT touched.
- `pending_sync_log`: device_id, batch_uuid, received_at, total, accepted, rejected, detail_json.
- `card_bind_sessions`: session_uuid, member_id, device_id, mode (`NEW_CARD|REPLACE_CARD|PIN_ONLY`), state (`WAITING_DEVICE|WAITING_CARD|WAITING_PIN|CONFIRM_PIN|DONE|FAILED|EXPIRED|CANCELLED`), uid_scanned, expires_at, created_by_admin_id, failure_reason.
- `operators`: operator_no (auto unique number starting at 1, typed on keypad), nama, operator_pin_hash (6-digit PIN, Argon2id), pin_fail_count, locked_until, is_active. Used for top-up authorization on Cashier (Section 6.7 and 14.10).
- `operator_devices`: operator_id FK, device_id FK (unique pair). Determines which operator may top-up on which Cashier.
- `topup_requests` (TopUpRequest): request_uuid (unique, idempotency; for CASHIER source = `txn_uuid`), member_id FK, amount (INTEGER), status (`COMPLETED|REVERSED`), source (`WEBUI|CASHIER`), device_id (nullable), processed_by_type (`ADMIN|OPERATOR`), processed_by_id, txn_id FK (unique, ledger `TOPUP` row), reversal_txn_id (nullable), reverse_reason (nullable), note.
- `audit_logs`: actor_type, actor_id, action, entity, entity_id, before_json, after_json, ip.
- `settings`: key-value (list in Section 10.7, changeable from WebUI).
- `catalog_meta`: single row, `version` INTEGER incremented on every product/slot change.

Required indexes: `transactions(member_id, occurred_at)`, `transactions(device_id, occurred_at)`, `cards(uid)`, `members(nik_idx)`, `topup_requests(member_id, created_at)`, `admin_sessions(session_hash)`.
Migrations via Alembic. Provide `tools/seed_data.py` (1 admin account from env, 20 members, 10 products, 1 cashier, 2 vendings, sample transactions).

**Atomic debit rule (mandatory):** all balance deductions use a single statement `UPDATE members SET balance = balance - :amt WHERE id = :id AND balance >= :amt` within a single DB transaction together with its ledger row; if `rowcount = 0` -> reject `INSUFFICIENT_BALANCE`. Reading balance then writing it back (race condition) is forbidden.

**Ledger invariant (mandatory test):** `member.balance == SUM(CREDIT) - SUM(DEBIT)` from transactions affecting balance, and `balance >= 0` always. Provide `python -m app.cli verify-ledger` command.

## 6. CASHIER FIRMWARE

### 6.1 Hardware: ESP32-WROOM-32 (D1 mini board format, 4MB flash)
- OLED SSD1306 128x64 I2C: SDA=GPIO21, SCL=GPIO22 (address 0x3C).
- RFID RC522 (SPI VSPI): SS=GPIO5, SCK=GPIO18, MOSI=GPIO23, MISO=GPIO19, RST=GPIO27.
- Keypad 4x4: Row = GPIO32, 25, 4, 0 (output) | **Col = GPIO26, 33, 17, 16** (input, all with internal pull-up).
- **Green server status LED**: GPIO13 (anode via 330 Ω resistor, cathode to GND).
- Active buzzer (optional): GPIO14. Code must still run if not installed.
- All pins in ONE file `include/pins_cashier.h`; no pin numbers outside that file.
- Pins available on the user's board header: IO0, 2, 4, 5, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33, 34, 35, plus JTAG pins (TDI=GPIO12, TDO=GPIO15, TMS=GPIO14, TCK=GPIO13) and SVP/SVN (GPIO36/39, input-only). Pins labeled SD1, SD2, SD3, CLK, CMD, SDD are connected to internal flash: FORBIDDEN to use. GPIO34, 35, 36, 39 are not used. Avoid GPIO12 and 15 (strapping) and GPIO2 unless forced. All assignments are in `pins_cashier.h`.

### 6.2 Mandatory hardware notes in `/docs/HARDWARE.md`
- **Keypad wire move** (mandatory from old wiring): Col3 from GPIO34 to **GPIO17**, and Col4 from GPIO5 to **GPIO16** (eliminating conflict with RC522 SS). Other wires unchanged. No time-multiplexing.
- GPIO34 is NOT USED (input-only and no internal pull-up). All keypad columns use pins with internal pull-up, so no external resistors needed. Firmware warns on serial if a column always reads LOW (indication of cable/short).
- GPIO0 (keypad row) and GPIO5 (SS) are strapping pins: do not press keypad buttons during boot/reset. Firmware holds all rows HIGH from the start of `setup()`.
- 3V3 and GND shared for OLED, RC522, and keypad.

### 6.3 Keypad Layout
1 2 3 A
4 5 6 B
7 8 9 C
· 0 # D

- `A`=Pay, `B`=Check Balance, `C`=Top-up (operator), `D`=Cancel/Back. `*`=delete one digit. `#`=OK/Enter. During PIN input, digits show as `*`.
- Scan keypad every 10 ms, debounce 30 ms; RFID poll every 100 ms only while waiting for card.
- Idle timeout on each input screen: 30 seconds, return to main screen.

### 6.4 Cashier Modes
One firmware, mode in `config.json` (LittleFS), changed via setup portal:
- **manual**: cashier enters amount (max 8 digits, `#` confirm), customer taps card then PIN.
- **scanner (remote)**: idle waiting for server command (remote binding, Section 7); Pay and Top-up menus disabled; Check Balance still available.
- On receiving bind command, device shows binding screen if not in transaction; if busy, replies `DEVICE_BUSY`.

### 6.5 Pay Flow (manual mode, ONLINE)
1. Main screen: `A:Bayar B:Saldo C:TopUp`.
2. `A` -> amount -> `#` -> `Total Rp X / Tempel kartu` (30 sec timeout).
3. Card read -> `Masukkan PIN` (server tracks `pin_fail_count`).
4. POST `/api/v1/payments` with new `txn_uuid`. Result: success (name, amount, remaining balance, beep), or specific error (insufficient balance, card inactive/locked, wrong PIN + attempts left, unknown card, member suspended).
5. If request times out: resend with SAME `txn_uuid` (idempotent) max 3x within 15 sec, then `GET /transactions/{txn_uuid}`. Never show "failed" before status is confirmed. If server unreachable and status cannot be determined, enter offline path (6.6) OR, if offline conditions not met, show `STATUS TIDAK PASTI, hubungi admin` + `txn_uuid`.

### 6.6 Cashier when OFFLINE (Pay and Check Balance only)
- Cashier uses the SAME offline engine as Vending (library `firmware-common`: 100-member cache, pending queue, PIN verifier, allowance rules; Section 10).
- Only applies if `offline_enabled=true` for that device (default true for Cashier manual mode).
- **Top-up, Card Binding, and PIN Reset: online-only.** When offline, screen shows `Butuh server`.
- Offline pay: manual amount must be <= `offline_txn_max` (Rp 30,000). If higher: `Nominal > batas offline`. Full rules in 10.2.
- Screen clearly shows `MODE OFFLINE` and estimated remaining balance label.
- Cashier cache = 100 members with most transactions on that Cashier (rule 10.1).

### 6.7 Top-up (Cashier manual, ONLINE)
`C` -> **operator code** (number, `#`) -> operator PIN 6 digits (shown as `*`) -> amount (multiple of 1,000, min `topup_min` 5,000, max `topup_max` 1,000,000) -> tap card -> member PIN -> server records `TOPUP` (CREDIT) and `topup_requests` row (`source=CASHIER`), `performed_by` = operator.
- Server validates: operator active and bound to this Cashier (Section 14.10). Five wrong operator PINs -> operator locked 15 minutes (`OPERATOR_LOCKED`).
- Cashier with no bound operator shows `Belum ada operator` when `C` is pressed.

### 6.8 Provisioning and Local Setup Portal
The Local Setup Portal is a small WebUI inside the device (module `provisioning` in `firmware-common`, used by Cashier and Vending) for initial configuration. It is separate from the server WebUI and has its own login.
- **First boot (not configured)**: device generates an 8-digit random **Setup Code**, displays it on screen (OLED/TFT) and serial, then opens WPA2 AP `MGROUP-CASHIER-XXXX` (XXXX = last 4 hex of MAC; Vending uses `MGROUP-VENDING-XXXX`) with password = Setup Code. LED blinks slowly.
- Portal at `http://192.168.4.1/`. Login: username `admin`, password = Setup Code (10-minute session; 5 failures -> 5-minute lock). Must change Setup Code on first login (8 digits, different from before). Stored as PBKDF2 hash + salt in NVS.
- Fields: up to 3 WiFi SSIDs + passwords, `server_url`, `server_url_fallback` (optional, e.g. other IP or `mgroup.local`), `device_id`, **Device Key** (both from server WebUI), mode (Cashier only: `manual` or `scanner`). Buttons: Test Connection (calls `GET /device/config` with entered credentials), Save and Reboot, Factory Reset. Portal never displays stored Device Key (field shows `••••`, empty = unchanged).
- **Re-entering Setup (device already configured)**: on main screen hold `D` + `*` for 5 seconds -> screen `Kode Setup:` (input 8 digits via keypad). Correct -> portal opens 10 minutes in AP+STA mode (AP with Setup Code password); during this time transactions are disabled. 3 failures -> 5-minute lock. Does not require server or connection.
- Forgot Setup Code: only recoverable by erasing flash via USB (written in firmware README). No backdoor.

### 6.9 Flash Partition (4MB, `partitions.csv`)
`nvs 20KB`, `otadata 8KB`, `app0 2MB`, `littlefs ~1.9MB`. Contains `/config.json`, `/cache/members.bin`, `/queue/pending.log`.

## 7. REMOTE CARD & PIN BINDING (via online Cashier)

### 7.1 Admin WebUI Flow
1. Admin searches member (name / member_code / exact NIK / UID) -> detail -> **Manage Card**.
2. Choose mode: `Kartu Baru`, `Ganti Kartu` (old card becomes `REPLACED`), or `Reset PIN saja`.
3. "Select Cashier" dropdown shows ALL devices of type `cashier` that are online (`ws_connected=true`), both `manual` and `scanner` modes, with realtime indicator (HTMX polling 3 sec). Admin may choose any Cashier, usually the closest to their location. Busy Cashiers appear disabled with label `Sibuk`; offline Cashiers are not shown.
4. Admin clicks **Scan**: server creates `card_bind_sessions` (90 sec expiry) and sends WS `bind.start` to the selected Cashier, which immediately shows instructions to the member (Section 7.2): tap card, then enter PIN. WebUI shows realtime progress. **Cancel** button available. Same flow for new member registration, Card Replacement, and PIN Reset.
5. Done: success (UID half-masked, status ACTIVE) or failure + reason.

### 7.2 Device Flow
- Screen 1: `Silahkan tempelkan kartu` (member name shown on top line; instruction addressed to the member standing at the Cashier).
- Card read -> `bind.card_scanned`. UID conflict -> `bind.error`, show `Kartu sudah terdaftar`.
- `Buat PIN 4 digit` -> `#`; `Ulangi PIN` -> `#`. Mismatch: retry (max 3x then session fails).
- `bind.pin_submitted` only after confirmation matches. Server hashes (Argon2id + PBKDF2 verifier), card `ACTIVE`, replies `bind.done`.
- `D` any time = cancel (`bind.cancel`).

### 7.3 Server Rules
- One active session per device and per member.
- `Ganti Kartu`: old card -> `REPLACED`, new card ACTIVE, balance unchanged, in ONE DB transaction. Delete old card's `offline_allowances`, send `cache.invalidate` to all units.
- `EXPIRED` sessions handled automatically by background task; device receives `bind.cancel`.
- All sessions recorded in audit log.

### 7.4 `PIN_ONLY` Mode
Tap a registered card belonging to that member (UID matches an ACTIVE/LOCKED card) then create new PIN twice. `LOCKED` card returns to `ACTIVE`, `pin_fail_count=0`.

### 7.5 Card Status Management (WebUI)
- Admin: `Nonaktifkan` (reason required: lost, damaged, other), `Aktifkan`, `Unlock`.
- Status change sent immediately to all units via WS `card.status_changed` and cache delta. Online payments immediately rejected by server. For units currently offline see 10.5.

## 8. CHECK BALANCE (Cashier & Vending)

Identical flow: Check Balance menu -> tap card -> 4-digit PIN -> show name and balance (OLED / TFT) for 10 seconds or until any button. No history on device.
- Online: POST `/api/v1/balance-check`.
- Offline (offline-capable units): from cache; show `Saldo (offline, per HH:MM)` = `balance_snapshot - offline_spent_local`.
- Does not create ledger row; recorded in `audit_logs` (`balance_check`) without amount.

## 9. VENDING FIRMWARE

### 9.1 Hardware: ESP32-S3 DevKitC-1 N16R8 (16MB flash, 8MB octal PSRAM)
GPIO33-37 used by PSRAM, GPIO19/20 USB: DO NOT USE. All pins in `include/pins_vending.h`.
- TFT ILI9341 2.8" 320x240 SPI: SCK=12, MOSI=11, MISO=13, CS=10, DC=9, RST=8, BL=14.
- RFID RC522 (second SPI bus): SCK=18, MOSI=17, MISO=16, SS=15, RST=7.
- Keypad 4x4: Row = 1, 2, 3, 4 (output) | Col = 5, 6, 38, 39 (input internal pull-up). Button functions: `A`=Buy, `B`=Check Balance, `D`=Cancel, `#`=OK, `*`=delete, digits = slot number or PIN.
- **Dispenser: 5x SG90 standard 180° positional servos** (SLOT_COUNT=5). Servo signals: slot1=GPIO40, slot2=GPIO41, slot3=GPIO42, slot4=GPIO21, slot5=GPIO47.
- **Green server status LED**: GPIO46 (anode via 330 Ω, cathode GND). Onboard RGB LED not used.
- No buzzer and no drop sensor in this stage (`has_drop_sensor=false`; dispense considered successful after servo motion completes).
- Wiring note (HARDWARE.md): servos MUST be powered from a separate 5V supply of at least 2A (not from board/USB 5V pin), GND common with ESP32, 470-1000 µF capacitor on 5V servo rail. 3.3V signal from ESP32 is sufficient for SG90.
- Do not press keypad during boot (GPIO3 strapping).

### 9.2 Dispenser Driver
- Interface `IDispenser { bool dispense(slot_no); }`. Current implementation: `ServoDispenser`. (Other drivers like shift register are out of scope for v1.3, but the interface must allow them.)
- `ServoDispenser`: 50 Hz PWM, pulse width 500-2400 µs (ESP32Servo). **Default v1.3: `positional` with standard SG90 180° servo.** Per-slot configuration (from `vending_slots`, synced via catalog):
  - `positional` (DEFAULT): moves from `home_deg` (default 0) to `dispense_deg` (default 90) **clockwise**, holds `hold_ms` (default 700), then returns to `home_deg`. **One cycle = one product out.**
  - `continuous` (option, not default): rotate pulse 1700 µs for `run_ms` (default 1000), then stop at 1500 µs.
- Only ONE servo moves at a time (mutex). Servo is attached only during dispense and detached afterward (no jitter, saves current). On boot servos are NOT moved.
- **Each transaction buys ONLY ONE product** (one slot, one servo cycle). Multi-product per transaction is out of scope for v1.3.
- Dispense result `ok|failed` (failed on mutex timeout / servo error); if a drop sensor exists, `failed` if not detected within 3 seconds.

### 9.3 Flash Partition (16MB, `partitions.csv`)
`nvs 24KB`, `otadata 8KB`, `app0 3MB`, `app1 3MB`, `littlefs ~9.5MB`. Contains `/config.json`, `/catalog.json`, `/img/<product_id>_<hash8>.jpg`, `/cache/members.bin`, `/queue/pending.log`.

### 9.4 Catalog & Images
- `GET /api/v1/vending/catalog?since=<version>` -> `{version, slot_count, slots:[{slot_no, product_id, name, price, stock, is_active, image_hash, image_sha256, image_size, image_url, servo_type, home_deg, dispense_deg, hold_ms, run_ms}]}`; 304 if unchanged.
- Images: server converts uploads to JPEG 160x160 (center crop), quality 80, max 20KB, filename contains 8-char sha256. Vending only downloads images whose hash is missing and deletes orphan images. Download goes to `.part` file, verified for size and full SHA-256, then atomic rename; on failure `.part` deleted, old image NOT touched, retry with 5 sec to 5 min backoff; LittleFS space checked (remaining >= size + 64KB, otherwise delete orphans, still insufficient -> report `LITTLEFS_FULL`). Status reported via heartbeat. Full flow in Section 14.11.
- Catalog sync every 60 sec when online + on WS `catalog.changed`. Atomic update (temp file then rename).
- Server stock reduced when transaction `COMPLETED` (online or sync). Vending also reduces local stock on dispense. Server stock wins on sync; stock must not go negative; slot with stock 0 shows `HABIS`.

### 9.5 Buy Flow
1. Main screen: grid of 5 products (image, name, price, slot number, `HABIS`, or `TIDAK TERSEDIA` if product inactive).
2. Select slot number (`#` confirm, `D` cancel) -> confirmation screen.
   One transaction is for ONE product only. No cart or multi-product purchase in v1.3.
3. Tap card -> 4-digit PIN.
4. ONLINE: POST `/api/v1/vending/payments`. Server debits atomically and creates `PENDING_DISPENSE` transaction; device dispenses then POST `/vending/payments/{txn_uuid}/dispense-result`. `ok` -> `COMPLETED`, stock reduced. `failed` -> automatic full REFUND, original status `DISPENSE_FAILED`.
5. Reset/power loss during `PENDING_DISPENSE`: on boot device reads `/queue/state.json` and reports `unknown`; server auto-REFUNDs `PENDING_DISPENSE` transactions older than 2 minutes without result.
6. OFFLINE: Section 10.

### 9.6 Screen & Security
- Status screen: WiFi icon, WS, pending queue count. 60-sec idle returns to main; backlight dims at 120 sec.
- `cache/members.bin` encrypted with AES-256-GCM using a per-device key generated at provisioning and stored in NVS. For production, document (optional) enabling flash encryption and secure boot.
- Serial log does not print full UID, PIN, or hash.

### 9.7 Vending Provisioning
Identical to Section 6.8 (same `provisioning` module), with differences: AP SSID `MGROUP-VENDING-XXXX`; no mode option; `has_drop_sensor` field (true or false); effective slot count comes from server (`slot_count`), not portal. AES-256 cache encryption key generated automatically and stored in NVS on first boot (never displayed). Re-enter Setup: hold `D` + `*` 5 sec on main screen then enter Setup Code.

## 10. OFFLINE RESILIENCE (VENDING and CASHIER, same engine)

### 10.1 100-Member Cache and Allowance
- Server computes per device: 100 members with most `PAYMENT` `COMPLETED` transactions on that unit in the last 60 days (ties: most recent wins; if fewer than 100, fill with most recently transacting members on any unit, up to 100). Only `ACTIVE` cards and `ACTIVE` members.
- Entry contents: `uid`, `member_code`, `name`, `balance_snapshot`, `snapshot_ts`, `offline_allowance`, `pin_verifier`, `pin_salt`, `card_status`, `local_fail_count`, `entry_version`. NO NIK or phone.
- `pin_verifier` = `PBKDF2-HMAC-SHA256(PIN, pin_salt, 20000 iterations)` (separate from server Argon2id; computed server-side when PIN is set; stored in `cards.offline_verifier`, never shown in WebUI).
- **Allowance** = offline spending cap for that card on that unit. Computed by server: `allowance = min(offline_card_cap, floor(balance / N))`, with N = number of offline-capable units caching that member (so total allowance across units <= balance). Stored in `offline_allowances`.
- **Every time member balance changes** (payment, top-up, refund, adjustment), server recomputes allowance for all units and orders updates via WS `cache.update` to online units.
- `offline_hold_mode`:
  - `soft` (DEFAULT): online payments may use full balance; allowance shrinks and is sent to online units. Residual risk: offline units still hold old allowance.
  - `hard`: funds equal to total allowance are HELD; online payment may only use `balance - SUM(allowance)`, so offline loss is zero (but part of balance is unusable online while member is cached).
- Cache sync: delta every 5 min (`GET /api/v1/device/member-cache?since=<cache_version>`), on WS `cache.invalidate` / `cache.update` / `card.status_changed`. Every successful online payment updates that member's entry.

### 10.2 Offline Transaction Rules
A unit is considered offline if REST/WS fails 2 consecutive times or WS disconnected > 10 seconds. Offline payment allowed ONLY if ALL true:
1. `offline_enabled=true` for that unit and clock is valid (NTP succeeded since last boot or stored in RTC/NVS).
2. UID is in cache and `card_status == ACTIVE`.
3. PIN matches `pin_verifier` (3 consecutive failures -> entry locked locally until server allows).
4. `price <= offline_txn_max` (default **Rp 30,000**).
5. `offline_spent_local(uid) + price <= offline_allowance` (i.e. insufficient balance -> REJECT, show `Saldo/limit offline tidak cukup`).
6. Time since `last_successful_sync` <= `offline_max_window` (default 24 hours), if exceeded: `Mode offline kedaluwarsa`.
7. Queue length < `offline_queue_max` (default 500).

### 10.3 Pending Transaction Queue
- Append-only `/queue/pending.log` (one JSON per line + CRC32), fsync on every write; survives power loss (corrupt lines ignored and reported).
- Contents: `txn_uuid`, `uid`, `slot_no`/`manual_amount`, `product_id`, `price`, `offline_ts`, `ts_untrusted`, `dispense_result`, `pin_fail_events`.
- `txn_uuid` = `<device_id>-<boot_counter>-<seq>-<rand8>`; `boot_counter` and `seq` in NVS (monotonic).

### 10.4 Reconciliation and NO-NEGATIVE-BALANCE GUARANTEE
- `POST /api/v1/device/sync` (batch <= 50), idempotent per `txn_uuid`, processed IN ORDER of `offline_ts`. Per-item reply: `ACCEPTED`, `DUPLICATE` (treated as success), `REJECTED(reason)`.
- Each item executed with atomic debit (Section 5). **If balance insufficient at sync: transaction REJECTED** (`status=REJECTED`, `reject_reason=INSUFFICIENT_AT_SYNC`), member balance NOT changed, and `shortfall_records` (`OPEN`) created with unit, member, amount, time. Balance never negative.
- This case should be very rare thanks to allowance (10.1). Only occurs if member spends balance online while another offline unit still holds old allowance (mode `soft`). Maximum loss per event capped by `offline_card_cap`. Mode `hard` eliminates it.
- WebUI provides tab **Laporan > Selisih/Kerugian** (list of `shortfall_records`, mark `RESOLVED` + note by admin). No automatic debt feature.
- Other rejections: UID never existed, `txn_uuid` conflicts with different payload, `offline_ts` in the future > 5 minutes. Appear in Laporan > Antrean Bermasalah.
- Failed dispense offline: sent with `dispense_result=failed`; server records PAYMENT then REFUND.
- After batch, unit deletes `ACCEPTED/DUPLICATE` items, replaces cache entries with new data (balance, allowance), and resets `offline_spent_local`.

### 10.5 Card Inactive/Lost while Unit Offline
Offline unit does not know new blocks. Therefore primary strategy is PREVENTING offline (Section 11) and limiting exposure via `offline_txn_max`, allowance, and `offline_max_window`. After going online, blacklist applies immediately and offline transactions from `INACTIVE` cards are still recorded with `card_inactive_at_sync=true` and shown in review reports. This risk is documented in SECURITY.md.

### 10.6 Offline PIN Failures
Each offline wrong PIN recorded (`pin_fail_events`) and sent at sync; server increments `pin_fail_count` and locks card when total reaches 3.

### 10.7 Settings (`settings` table, per-device override via `config_json`)
`offline_hold_mode=soft`, `offline_txn_max=30000`, `offline_card_cap=50000`, `offline_max_window_h=24`, `offline_queue_max=500`, `topup_min=5000`, `topup_max=1000000`, `device_offline_alert_s=120`, `session_idle_min=1440`.

## 11. ANTI-OFFLINE: AGGRESSIVE RECONNECT & LED SIGNAL (Cashier and Vending)

Modules `net_manager` and `status_led` in `firmware-common`, pure logic separated from I/O and natively tested.

### 11.1 Green LED Signal (single LED)
| Condition | Pattern |
|---|---|
| ONLINE (WiFi connected, WS connected, `hello_ok` received) | Solid on |
| OFFLINE / reconnecting (WiFi or server unreachable) | Fast blink (5 Hz) |
| Provisioning / AP setup mode | Slow blink (1 Hz) |
| Off | No power or firmware hung |
LED pattern must not be blocked by transactions (runs in separate task/timer). Besides LED, main screen always shows status icon.

### 11.2 Detection and Recovery
- Application heartbeat over WS: `ping` every 10 sec; unit considers WS dead if no `pong` within 25 sec then forces reconnect. Server marks offline if no ping > 30 sec.
- WiFi: `WiFi.setSleep(false)`, `setAutoReconnect(true)`, max TX power, up to 3 backup SSIDs (tried in order), automatic DHCP renew. Server tried via `server_url`, then `server_url_fallback`, then `mgroup.local` (mDNS).
- Reconnect backoff: 1, 2, 4, 8, 15 sec (max 15, unlimited attempts).
- **Escalation ladder if offline persists:** 30 sec -> disconnect and reconnect WiFi; 2 min -> restart WiFi stack (`WiFi.mode(WIFI_OFF)` then STA); 5 min -> switch backup SSID; 10 min -> `ESP.restart()` (only if no transaction in progress and queue fsynced; max 1x per 10 min, counter in NVS).
- Task watchdog 30 sec; restart if free heap < 20 KB for 60 sec.
- Every ONLINE/OFFLINE transition reported to server (`device_events`) once reconnected, with duration.

### 11.3 Server Side
- WebUI Dashboard: units offline longer than `device_offline_alert_s` (default 120 sec) shown red; uptime report per unit (percentage online, disconnect count, longest outage).
- Optional webhook `ALERT_WEBHOOK_URL` (env): server POSTs JSON `{device, event, since}` when a unit goes offline past threshold and when it recovers.
- Infrastructure recommendations in DEPLOY.md: server on mini-PC/Raspberry Pi with UPS, LAN cable to router, static IP or DHCP reservation, quality AP with strong signal near units, local DNS/mDNS `mgroup.local`.

## 12. REST API (prefix `/api/v1`, JSON)

Uniform error format: `{"error": {"code": "INSUFFICIENT_BALANCE", "message": "...", "details": {}}}`. Required codes: `INVALID_PIN` (+`attempts_left`), `CARD_LOCKED`, `CARD_INACTIVE`, `CARD_UNKNOWN`, `MEMBER_SUSPENDED`, `INSUFFICIENT_BALANCE`, `OUT_OF_STOCK`, `DEVICE_BUSY`, `DEVICE_REVOKED`, `CLOCK_SKEW`, `VALIDATION_ERROR`, `DUPLICATE_TXN` (returns original result), `BIND_CONFLICT`, `OFFLINE_LIMIT`, `PRODUCT_INACTIVE`, `OPERATOR_INVALID`, `OPERATOR_LOCKED`. Indonesian messages in Section 14.14.

**Device (Bearer device_token)**
- `POST /payments` (Cashier), `POST /topups` (Cashier + `operator_no` + `operator_pin` + member `pin`), `POST /balance-check`, `GET /transactions/{txn_uuid}`
- `POST /vending/payments`, `POST /vending/payments/{txn_uuid}/dispense-result`, `GET /vending/catalog`, `GET /media/products/{file}`
- `POST /device/sync` (Cashier and Vending), `GET /device/member-cache`, `POST /device/heartbeat` (fw_version, hw_mac, mode, uptime, rssi, free_heap, queue_len, reconnect_count, catalog_version, images_ok, images_total, image_error, fs_free_kb), `GET /device/config`
- `WS /ws/device` (Section 13)

**Admin**: WebUI pages and routes defined fully in Section 14.3 (page map). `/admin/*` routes only accept session cookie, separate from device API, and do not appear in OpenAPI. Public: `GET /healthz`.

All device API endpoints have Pydantic schemas, auto OpenAPI (enabled when `ENABLE_API_DOCS=true`), and are documented in `/docs/API.md`.

## 13. WEBSOCKET PROTOCOL (`/ws/device`)

Envelope: `{"v":1, "id":"<uuid>", "type":"...", "ts":<epoch>, "data":{...}}`. Every server command message must be acked with `ack` (same id) within 5 seconds.

Device -> Server: `hello` (device_id, token, fw_version, mode), `ping` (10 sec), `bind.card_scanned`, `bind.pin_submitted`, `bind.cancel`, `status` (idle/busy).
Server -> Device: `hello_ok`, `pong`, `bind.start` (session_uuid, member_name, mode, timeout), `bind.error`, `bind.done`, `bind.cancel`, `catalog.changed`, `cache.invalidate` (uid-list or all), `cache.update` (uid, balance_snapshot, offline_allowance, card_status), `card.status_changed`, `config.changed`, `force_disconnect`.

One active connection per device (new connection disconnects the old one). Document all payloads in `WS_PROTOCOL.md`.

## 14. ADMIN WEBUI (Tailwind)

This section is the COMPLETE and binding WebUI specification. Do not add menus or features beyond this section. Canonical terms in Section 19.

### 14.1 Principles
- WebUI is server-rendered (Jinja2 + HTMX + Alpine.js), not SPA. `/admin/*` routes return full pages or HTML fragments (HTMX). The only admin JSON is dashboard chart data.
- All validation and business logic (balance, PIN, status, top-up) live in server `services/` layer. Routers are thin, templates only display. Preview numbers in browser (e.g. "balance after top-up") are visual aids only and recomputed by server.
- All dashboard and report numbers come from database queries at page render time. No hard-coded numbers.
- Authentication only via session cookie (Section 4.1). No Admin API Token.
- Every data-changing action is recorded in `audit_logs`.
- `/docs` and `/openapi.json` only active when env `ENABLE_API_DOCS=true`. `/admin/*` routes not in OpenAPI.
- Balance only changes via ledger service (Section 5). WebUI never writes `members.balance` directly.

### 14.2 Access
Only ONE admin account: owner and server manager, the only WebUI user. No roles and no staff accounts. Admin can do EVERYTHING: member, card, top-up (including reversal), balance adjustment, devices, operators, products, reports and export, system parameters, system info, and audit log. The only restriction is session: all `/admin/*` routes except login require a valid session (Section 14.5); without session server redirects to login. NIK is masked by default and shown in full only after admin presses Show (recorded in audit). "Operator" (cashier officer) is only an identity and PIN on the Cashier keypad; the person may be the same as admin, and Operator is not a WebUI account.

### 14.3 Menu Structure and Page Map

Sidebar (fixed order): 1 Dashboard, 2 Member, 3 Top Up, 4 Transactions, 5 Cashier, 6 Vending, 7 Reports, 8 Settings, then Logout at bottom of sidebar. No other menus. Products under Vending, Operators under Cashier, Shortfall/Queue/Uptime under Reports, Audit and Parameters under Settings. A small numeric badge on Reports menu shows count of OPEN Shortfall plus Problem Queue.

| Menu | Routes (all under `/admin`) | Function |
|---|---|---|
| Auth | `GET,POST /admin/login`, `POST /admin/logout` | Login (public) and logout |
| Dashboard | `GET /admin`, `GET /admin/dashboard/charts?days=7` (JSON), fragments `GET /admin/dashboard/devices`, `/activity`, `/alerts` | Summary |
| Member | `GET /admin/members`, `GET,POST /admin/members/new`, `GET /admin/members/{id}`, `GET,POST /admin/members/{id}/edit`, `POST /admin/members/{id}/status`, `POST /admin/members/{id}/reveal-nik`, `POST /admin/members/{id}/adjust` | List, registration wizard, detail, edit, status, NIK, balance adjustment |
| Card (inside Member) | `GET,POST /admin/members/{id}/card`, `GET /admin/bind-sessions/{uuid}` (polling 2 sec), `POST /admin/bind-sessions/{uuid}/cancel`, `POST /admin/cards/{id}/status` | Manage Card (Section 7) |
| Top Up | `GET /admin/topups`, `GET,POST /admin/topups/new`, `GET /admin/topups/{id}`, `POST /admin/topups/{id}/reverse` | List, add balance, detail, reverse |
| Transactions | `GET /admin/transactions`, `GET /admin/transactions/{id}`, `GET /admin/transactions/export?format=csv` or `xlsx` | Ledger, detail, export |
| Cashier | `GET /admin/cashiers`, `POST /admin/cashiers`, `GET /admin/cashiers/{id}`, `POST /admin/cashiers/{id}/edit`, `/rotate-key`, `/revoke`, `/config`, `GET /admin/cashiers/operators`, `POST /admin/operators`, `POST /admin/operators/{id}/edit`, `/pin`, `/bind`, `/unlock`, `/active` | Devices and operators |
| Vending | `GET /admin/vendings`, `POST /admin/vendings`, `GET /admin/vendings/{id}`, `POST /admin/vendings/{id}/edit`, `/rotate-key`, `/revoke`, `/config`, `/sync`, `POST /admin/vendings/{id}/slots/{slot_no}`, `/restock`, `GET /admin/vendings/products`, `POST /admin/products`, `POST /admin/products/{id}/edit`, `/image`, `/image/delete`, `/active`, `GET /admin/media/products/{file}` | Machines, slots, products, images |
| Reports | `GET /admin/reports/{type}?range=...&from=...&to=...&group=...&format=...`, `POST /admin/reports/shortfall/{id}/resolve` | Types: transaksi, topup, saldo-member, penjualan-produk, selisih, antrean-bermasalah, kartu-nonaktif, uptime |
| Settings | `GET /admin/settings` (Profile), `/admin/settings/password`, `/sessions`, `/system`, `/parameters`, `/audit` (and their POST variants) | See 14.13 |
| Public | `GET /healthz` | Returns `{"status":"ok"}` only |

### 14.4 Layout and UX
- Desktop (>= 1024 px): left sidebar, top header (page title, admin name, profile menu with Logout), centered content. Sidebar can collapse to icons only (state remembered in `localStorage`, wrapped in try/catch).
- Tablet (768-1023 px): sidebar collapsed by default. Smartphone (< 768 px): sidebar becomes drawer with hamburger button, single-column forms, tables horizontally scrollable inside their container with first column sticky. Page must not scroll horizontally.
- Tables: search (300 ms debounce via HTMX), filters, column sorting, server-side pagination (default 20 rows, options 20/50/100), result count shown, empty state ("Belum ada data").
- Short forms use modal dialogs (HTMX): add device, add/edit operator, add/edit product, quick top-up from member detail, balance adjustment, all confirmation dialogs. Dedicated pages: login, member registration wizard, member detail and edit, new top-up, device detail, reports.
- Notifications for EVERY action: success toast (green, auto-dismiss 4 sec) or failure toast (red, stays until closed). For HTMX via `HX-Trigger` header, for non-HTMX via flash message.
- Sensitive actions (deactivate card, deactivate member, rotate/revoke Device Key, reverse top-up, balance adjustment) use confirmation dialog, with mandatory reason field where mentioned in the related section.
- Submit button disabled after click. All POST that changes money carries `request_uuid` (hidden field generated at form render) as idempotency key.
- Format: Rupiah `Rp 15.000` (thousands separator, no decimals), date `02 Nov 2026 14:05` (WIB, UTC+7), Bahasa Indonesia, Asia/Jakarta timezone.
- Light mode only. Status colors: green = online/active, gray = inactive, yellow = locked/warning, red = offline/failed, ALWAYS accompanied by text (not color alone).
- Accessibility: labels on all fields, minimum 4.5:1 contrast, visible focus, keyboard operable.

### 14.5 Login and Session
- Page `/admin/login`: username, password, show/hide password button (eye icon, Alpine), Login button, generic error message `Username atau password salah` (does not distinguish cause), block message `Terlalu banyak percobaan, coba lagi dalam N menit`.
- After login go to `/admin` (or original target page via `next` parameter validated to be a relative path). If `must_change_password=true`, all other pages redirect to `/admin/settings/password` until password changed.
- Login once per session: session valid 24 hours since last activity (sliding, setting `session_idle_min=1440`): every page opened before session expires resets count back to 0, no absolute limit. Not opened for more than 24 hours -> session expires. Session expires -> redirect to login with message `Sesi berakhir, silakan login kembali` (for HTMX requests use `HX-Redirect` header).
- Logout = `POST /admin/logout` with CSRF: server revokes session (`revoked_at`), deletes cookie, redirects to login. Password change revokes all OTHER sessions.

### 14.6 Dashboard
First page after login. Auto-refresh: cards and alerts every 30 sec, device status every 10 sec (HTMX polling).

Six cards:

| Card | Definition |
|---|---|
| Total Members | Count of all members (small note: N active) |
| Total Balance | `SUM(members.balance)` |
| Total Cashier | Count of ACTIVE Cashier devices (note: N online) |
| Total Vending | Count of ACTIVE Vending devices (note: N online) |
| Transactions Today | Count of `PAYMENT` `COMPLETED` transactions today WIB (note: total amount) |
| Total Top Up | `SUM(amount)` of `TOPUP` `COMPLETED` transactions today WIB (note: top-up count) |

Four charts (local Chart.js, range selector 7 or 30 days, default 7, data from `/admin/dashboard/charts`, days without data = 0, empty state "Belum ada data"):
1. Daily transaction activity: line, count of `PAYMENT COMPLETED` per day.
2. Transaction value: bar, total `PAYMENT COMPLETED` amount per day.
3. Top-up value: bar, total `TOPUP COMPLETED` amount per day.
4. Transaction comparison per device: horizontal bar, count of `PAYMENT COMPLETED` per device in range.

Recent Activity: 15 combined rows from `transactions` and `audit_logs` (actions `member.create`, `member.update`, `card.bind`, `card.replace`, `card.status`, ...) sorted newest. Columns: Time, Member (Member UID + name), Activity Type (Payment, Top-up, Refund, Adjustment, Member registration, Card binding, Card replacement, Member data change, Card status), Device, Amount, Status. Each row links to its detail.

Device Status: Name, Device ID, Type, Status (Online/Offline + duration since change), Last communication (relative and absolute time). Online = WebSocket connected and last ping <= 30 sec; otherwise Offline. "Last communication" = `last_seen_at` (WS ping or REST request). Red row if Offline longer than `device_offline_alert_s`.

Alerts (hidden if 0): OPEN Shortfall, Problem Queue, slot stock < 2, long-offline units, locked cards. Each links to related page.

### 14.7 Member

**List** `/admin/members`. Columns: Member UID, Name, Phone, NFC, Balance, Status, Actions (Detail, Edit). NFC column shows card status (Active, Locked, Inactive, or `Belum ada kartu`) and last 4 chars of Card UID (`••••A1B2`).
- Single search box `q` matching: Member UID, name (contains, case-insensitive), phone (digits only, contains), Card UID (prefix or exact), NIK (exact, via blind index).
- Status filter (All, Active, Inactive) and Card filter (All, Active, Locked, Inactive, No card). Sort: name, balance, registration date. Pagination. Add Member button.
- Label "Aktif" = status `ACTIVE`, "Nonaktif" = `SUSPENDED`. Inactive member: all payments rejected (`MEMBER_SUSPENDED`) and removed from unit caches (`cache.invalidate`).

**Registration** (three-step wizard, page `/admin/members/new`):
1. **Member data**: Full name (required, 3-100 chars), NIK/KTP (required in WebUI, MANDATORY, filled ONCE, NO format validation (free string), unique; only NIK stored, no KTP photo or address), Phone (required; regex `^(\+62|62|0)8\d{8,12}$`, stored normalized to `08xxxxxxxxxx`), Notes (optional). Initial status always Active.
2. **Initial balance** (optional, default Rp 0, multiple of 1,000, max `topup_max`). If > 0 server creates `topup_requests` (note "Saldo awal") and ledger `TOPUP` IN THE SAME database transaction as member creation (one fails = both rollback). Reminder text: "Pastikan uang tunai sudah diterima".
   Click **Simpan dan Lanjut**: server validates, creates member (Member UID `MG-A00001`, etc.), records audit. Member immediately appears in list with NFC `Belum ada kartu`.
3. **Bind Card and PIN**: remote binding panel mode New Card (Section 7.1 steps 3-5): choose any online Cashier nearest, click Scan, realtime progress, Cancel. Admin does NOT type PIN; PIN is created by the member on the Cashier keypad (Section 7.2). Button "Lewati, pasang nanti" goes to member detail. Member without card cannot transact.
Member UID generated by server, not editable, and does not change when profile edited or card replaced.

**Detail** `/admin/members/{id}` (four groups):
- **A. Identity**: Member UID, Name, NIK (masked `3201••••••••1234`; Show button, recorded in audit), Phone, Status, Registration date, Notes.
- **B. Transaction identity**: Active card (Card UID half-masked), Card status (Active, Locked, Inactive, No card), PIN status (`Belum diatur`, `Sudah diatur`, `Terkunci`), binding date and Cashier used. Buttons: Manage Card (New Card, Replace Card, Reset PIN), Deactivate or Activate card (mandatory reason: lost, damaged, other), Unlock. Card History table: all cards including `REPLACED` (UID masked, status, binding date, replacement date, reason).
- **C. Finance**: Current balance, Total top-up (`SUM TOPUP COMPLETED`), Total spending (`SUM PAYMENT COMPLETED` minus `SUM REFUND`). Buttons Top Up (dialog) and Balance Adjustment (add or subtract direction, amount, mandatory reason; subtraction must not make balance less than 0; result is `ADJUSTMENT` ledger row). Balance Change History table: all member ledger rows (time, type, signed amount, balance before, balance after, device, status), paginated.
- **D. Activity**: tabs Payments, Top-ups, Devices used (per device: transaction count and last used). Columns time, device, amount, status.

**Edit**: Name, NIK, Phone, Notes, Status (Active/Inactive with reason). Member UID read-only. Card and PIN are NOT edited here; both via Manage Card. Audit records before/after, and NIK change written as `NIK diubah` without the value.

**NFC and PIN management** = Section 7 as-is: both registration and card replacement are done by admin via WebUI by choosing any online Cashier then clicking Scan. Server guarantees one Card UID cannot be linked to another member (`BIND_CONFLICT`). Lost or damaged card: Deactivate then Replace Card; Member UID, balance, and all transaction history remain. WebUI NEVER displays or accepts member PIN, only its status. Member PIN differs from Cashier operator PIN.

### 14.8 Top Up
Mechanism: member hands cash to admin, then admin records the balance increase in WebUI (top-up via Cashier is in Section 6.7). No other funding source or payment gateway.

Every successful top-up, from WebUI or Cashier, produces ONE `topup_requests` row (Section 5) linked 1:1 to a `TOPUP` ledger row.

**List** `/admin/topups`: ID (`TU-000123`), Member (name + Member UID), Amount, Time, Processed by (Admin, or `Operator <name>` for Cashier), Source (WebUI, or Cashier + device name), Status (Completed, Reversed), Actions (Detail, Reverse). Filters: period (today, yesterday, 7 days, 30 days, custom), member (`q`), source, status. Above the table: count and total amount of filtered results (excluding reversed).

**Form** `/admin/topups/new` (also opened with `?member={id}` from member detail):
1. Search member (`q`: name, Member UID, Card UID, phone; results appear live in dropdown).
2. Card info: name, Member UID, status, current balance.
3. Amount (number input plus quick buttons 5,000, 10,000, 20,000, 50,000, 100,000).
4. Preview "Estimated balance after top-up".
5. Confirm button -> dialog "Terima Rp X dari {nama}? Saldo menjadi Rp Y" -> Process.

**Server validation**:
- Member exists and status Active.
- Amount is integer, multiple of 1,000, minimum `topup_min` (5,000), maximum `topup_max`.
- `request_uuid` unique: double click, refresh, or resend returns previous result and does NOT add balance again.
- Single DB transaction: insert `topup_requests` + insert ledger `TOPUP` (CREDIT) + `UPDATE members SET balance = balance + :amt`. Then audit, recompute allowance, send WS `cache.update`.
- Mandatory passing example: balance Rp 10,000 + top-up Rp 5,000 = Rp 15,000.

Result: toast `Top-up Rp 5.000 berhasil. Saldo sekarang Rp 15.000`, plus summary (receipt) with Print button.

**Reverse top-up** (mandatory reason): only for status Completed and only if member balance >= amount. Effect: `ADJUSTMENT` ledger (DEBIT) with `ref_txn_id` to the top-up transaction, original top-up status becomes `REVERSED`, `topup_requests.status` becomes `REVERSED`. If balance insufficient: reject with message `Saldo member sudah terpakai. Gunakan Koreksi Saldo setelah verifikasi.`

**Detail**: all columns plus balance before and after, `txn_uuid`, notes, and reference to reversal transaction (if any).

### 14.9 Transactions
Read-only page over the ledger. No edit or delete.

**List** `/admin/transactions`. Columns: Transaction ID (`T-000001` from id), Date and time (`occurred_at`, WIB), Member UID, Name, Type (Payment, Top-up, Refund, Adjustment), Device (name + Device ID; `WebUI` for ADMIN source), Amount (credit green `+`, debit red `-`), Status (Completed, Pending dispense, Dispense failed, Reversed, Rejected).
**Filters**: `q` (Member UID or name), Transaction ID (`T-...` or `txn_uuid`), Type, Device, Date range (preset today/yesterday/7 days/30 days/custom), Status, Source (Online, Offline sync, Admin). Summary above table: row count, total debit, total credit. CSV and XLSX export per filter.

**Detail** `/admin/transactions/{id}`, groups (rows whose data is unavailable are hidden):
- Transaction: ID, `txn_uuid`, occurrence time, server receive time, type, status, source, rejection reason.
- Member: Member UID (link), name, Card UID (masked).
- Device: Device ID, type, name, operator (for Cashier top-up).
- Finance: balance before, amount, balance after.
- Items (Vending): product, slot, price at transaction time.
- Related: reference transaction (refund with original payment, top-up reversal).

Card replacement, profile change, and PIN reset do NOT break history because transactions are bound to `member_id` (and historical `card_id`).

### 14.10 Cashier

**List** `/admin/cashiers`: Device ID, Name, Type (Cashier), Status (Online/Offline), Operator (name of bound operator; more than 2 shown as `A, B +1`), Last active, Actions (Detail, Edit). Add Device button.

**Registration** (dialog): Name (required), Location (optional). Server generates Device ID (`CSH-001`, sequential, never reused, separate from hardware identity) and Device Key. Result dialog shows both ONCE with Copy button and warning `Simpan sekarang, Device Key tidak dapat dilihat lagi`, plus step summary: enter Device ID, Device Key, WiFi SSID, and server address in device Local Setup Portal (Section 6.8). Device authentication = Device Key.

**Actions**: Edit (name, location); Rotate Key (confirm; old key immediately invalid and device disconnected; new key shown once); Revoke (status `REVOKED`, device rejected and disconnected; reactivate via Rotate Key); Offline config (`offline_enabled`, `offline_txn_max`, `offline_card_cap`; empty = follow global settings; produces WS `config.changed`).

**Detail** `/admin/cashiers/{id}` with tabs:
- **Summary**: Device ID, Name, Location, Hardware identity (MAC, reported by device), Type, Connection status (+ since), Last communication, Last IP, RSSI, Firmware version, Mode (manual or scanner), Uptime, Pending queue, Reconnect count, Connected operators.
- **Operators**: bound operators, with bind and unbind actions.
- **History**: sub-tabs Top-up (from `topup_requests` for this device), Transactions (ledger for this device), Communication (`device_events`: ONLINE, OFFLINE, REBOOT, WIFI_RECONNECT + duration), Operator Activity (top-up per operator and failed operator login attempts from audit).
- **Configuration**: effective values (global or override).

**Operator Management** `/admin/cashiers/operators`. Operator = cashier officer with own identity, NOT a WebUI account (person may be the same as admin; Operator is only identity and PIN for top-up on Cashier keypad). List: Code, Name, Bound Cashier, Status (Active, Inactive, Locked), Actions.
- Add (dialog): Name, 6-digit PIN (typed by admin twice; rejected if `000000`, `123456`, or repeated digits), select bound Cashier (can be multiple). Operator Code is automatic number (starting at 1, unique) typed on Cashier keypad.
- Actions: Edit name and binding, Reset PIN, Deactivate, Unlock. Operator PIN never shown after saving.
- Rules: top-up on Cashier only by an active operator bound to that Cashier. Five wrong operator PINs -> operator locked 15 minutes (`OPERATOR_LOCKED`); admin can Unlock.
- Besides operator PIN, top-up always requires card tap and member PIN.

### 14.11 Vending

**Machine list** `/admin/vendings`: Device ID, Machine name, Status, Firmware, Last active, Actions (Detail, Edit). Registration and actions (Edit, Rotate Key, Revoke, Offline config) same as Cashier; Device ID in form `VND-001`; there is a Slot count field (default 5, 1-16).

**Machine detail** `/admin/vendings/{id}`, tabs:
- **Summary**: identity, MAC, status, firmware, IP, RSSI, uptime, pending queue, reconnect count.
- **Slots and Products**: table of slots 1..N: Slot, Product (dropdown of active products or empty), Price, Stock, Capacity, Servo type (`positional` or `continuous`), servo parameters (angle or duration). Actions: Restock (increase stock, max capacity) and Set Stock (correction). Every change recorded in audit (before/after), increments `catalog_meta.version`, and sends WS `catalog.changed`. Slots with stock less than 2 flagged. Stock, slot, and servo management fully supported (not optional).
- **Synchronization**: server catalog version vs device applied, images synced `X/Y`, last error, LittleFS free (KB), last sync time, **Sync now** button (sends `catalog.changed`). Data from heartbeat (Section 12).
- **History**: machine transactions, ONLINE/OFFLINE events, sync log (`pending_sync_log`).
- **Configuration**: like Cashier.

**Products** `/admin/vendings/products`: columns Product ID (`PRD-0001`), Image (48 px thumbnail), Name, Price, Installed at (machine/slot), Status, Actions.
- Form (dialog): Name (required, 2-40 chars), Price (integer Rp 100 to Rp 1,000,000), Description (optional, max 200 chars, WebUI only, not sent to device), Image (upload JPG/PNG/WebP max 5 MB, square preview before save, replace, delete), Status Active/Inactive.
- Products are not permanently deleted, only deactivated. Inactive products still installed in a slot show `TIDAK TERSEDIA` on the machine and payments rejected `PRODUCT_INACTIVE`. Price changes apply to new transactions; history uses price at transaction time (`items_json`).

**Image sync flow**:
1. Admin uploads or replaces image. Server converts to JPEG 160x160 (Section 9.4), computes full SHA-256 and first 8 hex (used in filename), stores in `server/data/media/products/`, and increments catalog version.
2. Catalog includes `image_url`, `image_hash`, `image_sha256`, `image_size` per slot.
3. Vending downloads to `.part` file, verifies size and full SHA-256, then atomic rename to `/img/<product_id>_<hash8>.jpg`.
4. Download or verification failure: `.part` deleted, old image NOT touched, retry with 5 sec to 5 min backoff, error reported via heartbeat (`image_error`).
5. Before download, device checks LittleFS free space (>= size + 64 KB). Insufficient: delete orphan images; still insufficient: report `LITTLEFS_FULL`. LittleFS partition already accounts for firmware size (Section 9.3); `pio run` must show firmware size fits the app partition.
6. Image changes (new hash) -> re-download, display, then delete old image after new one is valid. Product without image uses firmware built-in placeholder icon.
7. Communication uses the same API contract as Section 9.4 and 12.

### 14.12 Reports
`/admin/reports`, eight tabs: Transactions, Top-up, Member Balance, Product Sales, Shortfall/Loss, Problem Queue, Inactive Cards (Offline), Device Uptime.

**Period filter** (all tabs except current balance column on Member Balance): Today, Yesterday, Last 7 days, Last 30 days, Custom range (from-to, max 366 days). Day boundaries 00:00:00-23:59:59 WIB, stored UTC. Default: last 7 days.

- **Transactions**: Transaction count (`PAYMENT COMPLETED`), Total payments, Total refunds, Net sales. Grouping (Group by selector): Date, Device, Member (top 50 by amount).
- **Top-up**: Top-up count, Total amount (excluding reversed). Grouping: Date, Admin, Operator, Cashier (WebUI source counted as `WebUI`).
- **Member Balance**: Member UID, Name, Current balance, Total top-up (period), Total balance usage (period). Total circulating balance above table. Search and sort available.
- **Product Sales**: per product units sold and revenue, with per-machine breakdown.
- **Shortfall/Loss**: list of `shortfall_records` (Section 10.4), total OPEN, **Mark Resolved** action with mandatory note.
- **Problem Queue**: read-only list of sync transactions with status `REJECTED` other than Shortfall (unknown UID, `txn_uuid` conflict, future timestamp), with reason, device, and time.
- **Inactive Cards (Offline)**: transactions with `card_inactive_at_sync=true` (Section 10.5).
- **Device Uptime**: per unit online percentage, disconnect count, longest outage, total offline time (from `device_events`).

**Export**, all from backend queries, not computed in browser:
- CSV: UTF-8 with BOM, comma separator, Indonesian headers, numbers without thousands separators.
- Excel: `.xlsx` via `openpyxl`, one sheet per tab, amount columns formatted as Rupiah.
- Print: button calls `window.print()` with print stylesheet (sidebar and buttons hidden; title, period, print time, and printer name shown).
File name: `mgroup-<type>-<YYYYMMDD>-<YYYYMMDD>.<ext>`.

### 14.13 Settings (`/admin/settings`, tabbed)
- **Profile**: username, display name, last login, created date.
- **Change Password**: Old password, New password, Confirm (each with show/hide buttons). Server validates: old password correct, policy Section 4.1 met, confirmation matches, new differs from old. Stored Argon2id. Success -> other sessions revoked and `must_change_password=false`.
- **Login Sessions**: list of own active sessions (browser from short user-agent, IP, start, last activity, expiry, `Sesi ini` marker), End button per session and `Keluar dari semua perangkat lain`. Expiry and page protection per 14.5.
- **System Information**: System Name and Version (`APP_VERSION` from `pyproject.toml`), API Version (`v1`), DB Schema Version (Alembic head), Server time and timezone, Server uptime, Service status (Database OK + file size; WebSocket: connection count; background tasks: binding session expiry, `PENDING_DISPENSE` auto-refund, offline monitor, each with last run time; free disk space), Device summary (active and online Cashier and Vending counts, effective offline parameters), Last backup (from marker file written by `tools/backup.sh`).
- **System Parameters**: all values from Section 10.7 (including `topup_min`, `topup_max`, `session_idle_min`) with range validation. Changes trigger WS `config.changed` and recorded in audit.
- **Audit Log**: read-only list with filters (actor, action, entity, date), pagination, before/after detail (sensitive data masked).

### 14.14 Error Messages (server sends Indonesian message in `message` field; WebUI and devices use the same text)

| Code | Message |
|---|---|
| `INSUFFICIENT_BALANCE` | Saldo tidak cukup |
| `INVALID_PIN` | PIN salah. Sisa percobaan: N |
| `CARD_LOCKED` | Kartu terkunci. Hubungi admin |
| `CARD_INACTIVE` | Kartu tidak aktif |
| `CARD_UNKNOWN` | Kartu tidak terdaftar |
| `MEMBER_SUSPENDED` | Member nonaktif |
| `OUT_OF_STOCK` | Stok habis |
| `PRODUCT_INACTIVE` | Produk tidak tersedia |
| `DEVICE_BUSY` | Perangkat sedang sibuk |
| `BIND_CONFLICT` | Kartu sudah terdaftar pada member lain |
| `OPERATOR_INVALID` | Kode atau PIN operator salah |
| `OPERATOR_LOCKED` | Operator terkunci sementara |
| `VALIDATION_ERROR` | Per-field message, shown below related field and summarized in toast |
| `DUPLICATE_TXN` | Returns original transaction result |

## 15. DOCUMENTATION & QUALITY

- `README.md`: system overview, quick start (`docker compose up`), Cashier and Vending provisioning, architecture diagram (Mermaid).
- `ARCHITECTURE.md`: flow diagrams Pay, Binding, Offline sync, allowance, transaction and binding session state machines (Mermaid).
- `WEBUI.md`: page map, access matrix, and screenshots of each menu (taken with Playwright on seed data, 1280 and 390 px viewports).
- `HARDWARE.md`: pin tables for both units, wiring (including Col3 to GPIO17 and Col4 to GPIO16, separate servo supply), BOM.
- `SECURITY.md`: threat model, accepted risks (4-digit PIN, UID can be cloned, inactive card while offline, shortfall in soft mode).
- Configuration via `.env` (complete `.env.example`); no hard-coded secrets.
- Server logging JSON structured, no PIN/token/NIK.
- `tools/backup.sh` (SQLite `.backup` + media copy).
- `tools/device_simulator.py`: Cashier and Vending simulator (including offline, sync, WS disconnect-reconnect) for testing without hardware.

## 16. ACCEPTANCE CRITERIA (mandatory pass)

**Server (pytest, coverage >= 85% on services/routers):**
1. Successful payment reduces balance exactly and creates 1 ledger row; same `txn_uuid` does not debit twice.
2. Concurrency: 50 parallel payments on one member never produce wrong or negative balance; ledger invariant passes. `CHECK(balance >= 0)` holds (direct DB write of negative balance fails).
3. Insufficient balance (online) always `INSUFFICIENT_BALANCE`; debit adjustment that would make balance < 0 rejected.
4. 3 wrong PINs lock card; admin unlock; weak PIN rejected.
5. Binding: new card, replace card (balance unchanged, old card REPLACED), PIN-only, UID conflict, expired, cancel, device busy.
6. Allowance: sum of all member allowances <= balance at computation time; changes when balance changes; `cache.update` sent.
7. Offline sync: duplicate idempotent; `offline_ts` order respected; insufficient balance -> `REJECTED` + `shortfall_records`, balance unchanged; `hard` mode holds funds and rejects online payments exceeding allowance.
8. Failed dispense -> automatic refund; `PENDING_DISPENSE` > 2 minutes -> automatic refund.
9. Role and CSRF enforced; revoked device rejected (REST and WS).
10. ONLINE/OFFLINE events recorded; alert webhook sent (tested with mock).
11. `verify-ledger` passes; `ruff` clean; Alembic migration runs from empty DB.

**Firmware:**
12. All three projects (common, cashier, vending) build `pio run` successfully without critical warnings. No GPIO numbers outside pins files.
13. Pure logic (state machine, protocol parser, queue, PIN verifier, offline rules 10.2, reconnect escalation ladder 11.2, LED patterns 11.1, **ServoDispenser positional timing (0°→90°→hold→0°, one cycle per product)**) separated from I/O and has unit tests `pio test -e native`.
14. `device_simulator.py` end-to-end test: online pay, offline -> sync, shortfall, binding via WS, WS disconnect-reconnect.
15. Each firmware README: how to build, flash, provision, wiring table, how to recover forgotten Setup Code.
16. Local Setup Portal logic (Setup Code, 3x and 5x lockout, re-entry via `D`+`*`) separated from I/O and has native unit tests.
16b. Test: one vending transaction triggers ONLY ONE servo cycle (no multi-product).

**WebUI (pytest + httpx, plus Playwright smoke test for login and one top-up):**
17. All `/admin/*` routes except login redirect to login without session; `Authorization: Bearer ...` header rejected on `/admin/*`; Device Key does not work for admin and vice versa.
18. All `/admin/*` routes except login require session; no roles or other accounts; NIK masked by default and full only after Show button (recorded in audit); `python -m app.cli reset-admin-password` works.
19. Session: 24 hours since last activity and reset to 0 on every page open (no absolute limit), logout revokes session, password change revokes other sessions, `must_change_password` forces password change, login rate limit.
20. WebUI top-up: balance 10,000 + 5,000 = 15,000 with 1 `topup_requests` and 1 `TOPUP` ledger; resend with same `request_uuid` does not add balance; invalid amount and inactive member rejected; reversal only if balance sufficient; `verify-ledger` passes afterward.
21. Member registration: Member UID generated by server and unique; initial balance recorded as `TOPUP` in same DB transaction (one fails = both rollback); NIK duplicate rejected (uniqueness via blind index, no format validation); member list search finds via Member UID, name, phone, Card UID, and exact NIK.
22. Card replacement, profile change, and PIN reset do not change Member UID and do not break member transaction history.
23. Operator: correct code + PIN, bound vs unbound, 5x lockout, admin unlock; Cashier top-up creates `topup_requests` with source CASHIER.
24. Device: Device Key shown once; rotate and revoke take effect immediately (REST and WS); inactive product rejected `PRODUCT_INACTIVE`; failed image verification does not damage old image (tested in simulator); `image_sha256` correct.
25. Reports: each tab's numbers match manual ledger queries on seed data; period uses WIB day boundaries; CSV (BOM) and XLSX exports open and match display; print view available.
26. Dashboard: six cards and four charts come from database (tested with seed data); online/offline status matches `ws_connected` and `last_seen_at`.
27. Responsive: Playwright smoke test at 1280, 820, and 390 px viewports without horizontal scroll on pages (outside table containers).

## 17. DECISION LOG (defaults that APPLY; follow without asking)

| # | Decision |
|---|---|
| 1 | Cashier (manual mode) and Vending are both offline-capable for Pay and Check Balance, using the shared library. Top-up, Binding, PIN Reset are online-only. |
| 2 | Balance per member, one active card per member. |
| 3 | Top-up via Cashier (6-digit operator PIN) and admin WebUI. |
| 4 | Balance is NEVER negative. Offline transactions not covered by balance at sync are rejected and recorded in Shortfall/Loss. |
| 5 | Offline limits: Rp 30,000/transaction, allowance <= Rp 50,000/card/unit, 24-hour window, max queue 500. |
| 6 | Fund-hold mode default `soft`; `hard` available in settings. |
| 7 | Cache = top 100 members per unit, last 60 days. |
| 8 | Offline PIN verified via separate PBKDF2 verifier; cache encrypted with AES-GCM. |
| 9 | Communication: REST + WebSocket; per-device auth token; no MQTT. |
| 10 | Cashier: ESP32-WROOM-32 (38-pin user header). Col3=GPIO17, Col4=GPIO16; GPIO34 not used; LED GPIO13; buzzer GPIO14 (optional). |
| 11 | Vending: ESP32-S3 N16R8, TFT ILI9341; **5x SG90 standard 180° positional servos** (GPIO 40, 41, 42, 21, 47), default `home_deg=0`, `dispense_deg=90` clockwise, `hold_ms=700`, one cycle = one product; LED GPIO46; no buzzer and no drop sensor. |
| 12 | Firmware: Arduino + PlatformIO; no OTA in v1.3. |
| 13 | WebUI: Jinja2 + HTMX + Alpine + Tailwind standalone CLI, no CDN. |
| 14 | Product images 160x160 JPEG from server conversion. |
| 15 | Failed dispense -> automatic full refund. |
| 16 | Green LED: solid = online, fast blink = offline, slow blink = provisioning. |
| 17 | Anti-offline: 10 sec ping, WiFi escalation ladder up to 10-minute restart, backup SSID, backup server URL, WebUI alert + optional webhook. |
| 18 | All UI text Indonesian, code English, times UTC in DB. |
| 19 | Out of scope v1.3: QRIS/cash, OTA, multi-branch, mobile app, shift-register driver, automatic debt, Admin API Token. |
| 20 | Member UID = `member_code` `MG-A00001` to `MG-Z99999` (server-generated, fixed). Card UID = NFC HEX (replaceable). The term "NTR" does not exist. |
| 21 | Only ONE admin account (owner = server manager), no roles and no staff accounts; admin can do everything. "Operator" = cashier officer (code + 6-digit PIN on Cashier keypad), not a WebUI account, and may be the same person as admin. |
| 22 | Fixed sidebar: Dashboard, Member, Top Up, Transactions, Cashier, Vending, Reports, Settings, Logout. Products under Vending; Shortfall, Queue, Uptime under Reports; Audit and Parameters under Settings. |
| 23 | Top-up uses `topup_requests` table (1:1 with `TOPUP` ledger), status `COMPLETED` or `REVERSED`, source WebUI or Cashier. Reversal only if balance sufficient. |
| 24 | Initial member balance recorded as first top-up via ledger, not a free column. |
| 25 | NIK, name, and phone required at WebUI registration; only NIK stored. |
| 26 | Member card and PIN are bound (both registration and replacement) by admin via WebUI: admin chooses any online Cashier nearest, clicks Scan, then member taps card and creates PIN on that Cashier. Admin never types member PIN. |
| 27 | Operator: numeric Operator Code + 6-digit PIN, bound to specific Cashier, locked 15 minutes after 5 failures. |
| 28 | "Device local WebUI" = Local Setup Portal, the configuration WebUI of each Cashier and Vending unit itself (NOT the server WebUI), with 8-digit Setup Code; re-entry via `D`+`*` 5 sec; does not depend on server. |
| 29 | Device Key = `device_token`. Device ID `CSH-001` / `VND-001`. |
| 30 | Admin session: 24 hours since last activity (sliding, reset to 0 on every page open), no absolute limit. Admin password minimum 10 characters, letters + numbers. |
| 31 | Report export: CSV (UTF-8 BOM), XLSX, and print. Charts use local Chart.js. |
| 32 | Short forms = dialog; member wizard, detail, reports = pages. Table default 20 rows per page. |
| 33 | Products are not permanently deleted; inactive -> `TIDAK TERSEDIA` on machine and payment `PRODUCT_INACTIVE`. |
| 34 | One transaction = ONE product (one slot, one servo cycle). No multi-product/cart in v1.3. |
| 35 | NIK is mandatory, filled ONCE at registration, no format validation, unique (blind index), encrypted. |

## 18. ALLOWED WORK ORDER

Work sequentially and do not proceed until phase criteria pass: (1) Server core + DB + device auth + ledger + allowance, (2) WebSocket + binding + offline sync, (3) Admin WebUI (3a: layout, login, dashboard, member, top-up, transactions; 3b: cashier, operator, vending and products, reports, settings, export), (4) firmware-common (net_manager, LED, queue, cache, verifier, provisioning, keypad) + native tests, (5) Cashier Firmware, (6) Vending Firmware (servo, catalog, images), (7) Simulator + documentation + hardening. After each phase write a short summary in `/docs/PROGRESS.md` (what is done, test results, new assumptions).

## 19. GLOSSARY (canonical terms; use consistently in code, UI, and documentation)

| Term | Meaning |
|---|---|
| Member UID | `members.member_code`, format `MG-A00001` to `MG-Z99999` (rule in Section 1). Server-generated, unchangeable, never reused. Primary member identity. |
| Card UID | NFC UID HEX code (`cards.uid`). Physical card identity; can be replaced without changing Member UID. |
| NFC / Card | Physical card linked to one Member UID. |
| Member PIN | 4-digit transaction PIN, created by the member on the Cashier keypad. Admin never sees or types it. |
| Operator | Cashier officer with Operator Code (numeric) and 6-digit Operator PIN. NOT a WebUI account. |
| Admin | Single WebUI account (owner and server manager), no role. |
| Device ID | Server-generated device ID: `CSH-001` (Cashier), `VND-001` (Vending). |
| Device Key | Device authentication key (= `device_token`, Section 4.2). Shown once at creation or rotation. |
| Setup Code | 8-digit numeric code to access the Local Setup Portal and the setup AP password. |
| Local Setup Portal | "Device local WebUI": the configuration WebUI of each Cashier and Vending unit itself, NOT the server WebUI (Sections 6.8 and 9.7), with its own login. |
| TopUpRequest | A row in `topup_requests` table, one per top-up (WebUI or Cashier), linked 1:1 to a `TOPUP` ledger row. |
| Transaction ID | `T-` + 6-digit `transactions.id` (e.g. `T-000123`). Top-up ID: `TU-` + 6 digits. Product ID: `PRD-0001`. |
| Allowance | Offline spending cap per card per unit (Section 10.1). |
| Shortfall/Loss | Offline transaction rejected at sync due to insufficient balance (Section 10.4). |
| Online / Offline (unit) | Online = WebSocket connected and last ping <= 30 seconds. |
| Cashier / Vending | Two types of ESP32 units (Sections 6 and 9). |
| NIK | Nomor Induk Kependudukan. Mandatory, filled ONCE at registration, no format validation, unique, encrypted. |
