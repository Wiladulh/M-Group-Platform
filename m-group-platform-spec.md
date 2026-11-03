Berikut file lengkap m-group-platform-spec-v1.3.md dalam bahasa Inggris, sudah menggabungkan semua patch v1.2 → v1.3. Tinggal copy-paste utuh ke OpenHands. 

markdown
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
/firmware-common/ (shared PlatformIO library: net_manager, status_led, offline_queue, member_cache, pin_verifier, protocol, provisioning, keypad, util; + native tests)
/firmware-cashier/ (PlatformIO: platformio.ini, src/, include/, README.md; uses ../firmware-common via lib_extra_dirs)
/firmware-vending/ (PlatformIO: platformio.ini, src/, include/, data/, partitions.csv, README.md; uses ../firmware-common)
/docs/ (ARCHITECTURE.md, API.md, WS_PROTOCOL.md, DB_SCHEMA.md, HARDWARE.md, SECURITY.md, ASSUMPTIONS.md, DEPLOY.md, PROGRESS.md, WEBUI.md)
/tools/ (seed_data.py, device_simulator.py, backup.sh)
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
- `members`: member_code (un


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
- **scanner (remote)** : idle waiting for server command (remote binding, Section 7); Pay and Top-up menus disabled; Check Balance still available.
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
- **First boot (not configured)** : device generates an 8-digit random **Setup Code**, displays it on screen (OLED/TFT) and serial, then opens WPA2 AP `MGROUP-CASHIER-XXXX` (XXXX = last 4 hex of MAC; Vending uses `MGROUP-VENDING-XXXX`) with password = Setup Code. LED blinks slowly.
- Portal at `http://192.168.4.1/`. Login: username `admin`, password = Setup Code (10-minute session; 5 failures -> 5-minute lock). Must change Setup Code on first login (8 digits, different from before). Stored as PBKDF2 hash + salt in NVS.
- Fields: up to 3 WiFi SSIDs + passwords, `server_url`, `server_url_fallback` (optional, e.g. other IP or `mgroup.local`), `device_id`, **Device Key** (both from server WebUI), mode (Cashier only: `manual` or `scanner`). Buttons: Test Connection (calls `GET /device/config` with entered credentials), Save and Reboot, Factory Reset. Portal never displays stored Device Key (field shows `••••`, empty = unchanged).
- **Re-entering Setup (device already configured)** : on main screen hold `D` + `*` for 5 seconds -> screen `Kode Setup:` (input 8 digits via keypad). Correct -> portal opens 10 minutes in AP+STA mode (AP with Setup Code password); during this time transactions are disabled. 3 failures -> 5-minute lock. Does not require server or connection.
- Forgot Setup Code: only recoverable by erasing flash via USB (written in firmware README). No backdoor. 

### 6.9 Flash Partition (4MB, `partitions.csv`)
`nvs 20KB`, `otadata 8KB`, `app0 2MB`, `littlefs ~1.9MB`. Contains `/config.json`, `/cache/members.bin`, `/queue/pending.log`. 

## 7. REMOTE CARD & PIN BINDING (via online Cashier) 

### 7.1 Admin WebUI Flow
1. Admin searches member (name / member_code / exact NIK / UID) -> detail -> **Manage Card**.
2. Choose mode: `Kartu Baru`, `Ganti Kartu` (old card becomes `REPLACED`), or `Reset PIN saja`.
3. "Select Cashier" dropdown shows ALL devices of type `cashier` that are online
