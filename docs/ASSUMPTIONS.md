# Asumsi Implementasi

> Every time the spec is ambiguous, choose the simplest safe option, record it here, and continue. Do not stop to ask.

## Catatan asumsi
- Setiap keputusan tambahan dicatat di bawah fase terkait.

## P1.5
- app/config.py sudah memiliki default untuk seluruh setting yang digunakan; .env.test tidak diperlukan.
- Menambahkan python-dotenv karena Pydantic Settings membaca env_file=".env".
- Ruff import grouping diperbaiki secara minimal; logika tidak berubah.
- CI tidak menyimpan DATA_KEY produksi; key pengujian dibuat acak per proses.
- Root .gitignore dibuat; server/.gitignore dipertahankan.

## P2
- Enum/status disimpan sebagai String dengan CHECK constraints agar validasi ditegakkan SQLite.
- JSON payload disimpan sebagai TEXT; encoding/decoding menjadi tanggung jawab lapisan aplikasi.
- DateTime(timezone=True) digunakan; SQLite tidak memiliki tipe timestamp ber-timezone native, sehingga aplikasi wajib menulis/membaca UTC.
- Kolom non-null mengikuti spesifikasi; default sederhana seperti status ACTIVE dan counter 0 dipasang bila aman.
- catalog_meta dan admin_users singleton ditegakkan dengan CHECK(id = 1).
- Migration test memakai SQLite in-memory; WAL tidak didukung in-memory, sedangkan engine aplikasi file-backed mengaktifkan WAL.
- FK memakai ON DELETE RESTRICT untuk melindungi histori transaksi/audit.

## P2.1 — DATA_KEY test isolation
- DATA_KEY wajib valid Base64 yang mendekode tepat 32 byte; pytest membuat key acak per sesi.

## P3 — Security primitives
- Argon2id memakai parameter default modern dari argon2-cffi karena spesifikasi tidak menentukan angka parameter.
- DATA_KEY dan PIN_PEPPER adalah secret independen dan tidak boleh masuk repository atau log.

## P4 — Ledger dan Allowance MVP
- SQLite concurrency test memakai file-backed database, WAL, busy_timeout 30000, dan BEGIN IMMEDIATE untuk menghindari deferred read-to-write lock upgrade.
- Denominator allowance MVP diproksikan sebagai jumlah device ACTIVE dengan config_json.offline_enabled=true; P9 menggantinya dengan cache membership aktual.
- N=0 menghasilkan mapping kosong; tidak ada pembagian nol atau allowance fiktif.
- Perubahan saldo menghitung ulang allowance dalam transaksi ledger yang sama.
- Reversal menambah baris ADJUSTMENT; original tidak diubah. Refund otomatis menggunakan source ADMIN karena CHECK schema membatasi source.
- REJECTED tidak memengaruhi invariant saldo.

## P5 — Device authentication, config, dan seed
- Global setting dibaca dari tabel settings dan di-cast mengikuti tipe default; nilai device.config_json menimpa nilai global. Field device_config_overrides mengembalikan dictionary override yang tersimpan, bukan seluruh effective config.
- Seed P5 menetapkan offline_enabled=true untuk ketiga device development agar allowance MVP P4 mengenali device tersebut. Nilai ini dapat diubah melalui config_json.
- Device config default offline_enabled=true untuk kedua jenis device; spesifikasi menyebut Cashier manual default true dan Vending mengikuti kemampuan offline-first. Admin dapat menonaktifkan per device melalui config_json.
- Cashier mode awal disimpan di reported_mode="manual"; override config_json.mode mengalahkan nilai tersebut. Vending mengembalikan mode=null dan slot_count.
- Device Key hanya dicetak untuk device yang baru dibuat; seed kedua kali tidak dapat menampilkan ulang key karena database hanya menyimpan hash.
- P5 tidak menambah endpoint atau token Admin. P14 wajib memastikan semua route /admin/* hanya menerima session cookie dan menolak header Authorization (Section 16 #17).
- CLOCK_SKEW disediakan sebagai domain error handler 409; pemeriksaan timestamp request akan diterapkan pada fase transaksi.
- Failed authentication does not update last_seen_at/last_ip; successful authentication schedules a presence update only after ACTIVE status and token verification.

## P3 patch — reject all-zero DATA_KEY
- Settings.data_key dan _load_fernet_key() sama-sama menolak key Base64 yang mendekode menjadi 32 byte nol; key wajib berisi setidaknya satu byte non-zero.
- Regression tests mencakup validator Settings, loader Fernet, key acak 32 byte, dan key acak per-session pytest.

## Coverage patch — measure the complete app package
- Pytest coverage scope diperluas dari `app/security` menjadi seluruh package `app` (`--cov=app`); threshold tetap 70% dan tidak ada module yang dikecualikan.
- Hasil CI scope seluruh `app` setelah P4: **89,44%** (881 statements, 93 missed), 90 tests passed. Tidak ada module di bawah 70%; terendah `app/cli.py` 72%, `app/services/settings.py` 73%, dan `app/services/ledger.py` 75%.

## P4 patch — composable ledger mutations
- `_debit_internal()` dan `_credit_internal()` hanya boleh dipanggil di dalam transaksi aktif; keduanya tidak melakukan commit/rollback. Caller bertanggung jawab membungkus seluruh perubahan ledger, allowance, dan co-write (misalnya audit/PIN reset) dalam satu `session.begin()`.
- Public `debit()` dan `credit()` tetap aman secara default dan tetap membuka satu transaksi sendiri sebelum memanggil method internal.
- `reverse()` dan metode perubahan status dispense tetap memiliki transaksi sendiri; akan direfaktor saat komposisi dibutuhkan oleh P6 vending atau P8 admin topup.

## P5 patch — isolated device-auth session
- Device authentication performs its SELECT in a dedicated `get_auth_session()`; the dependency always closes that session and never commits it.
- Authentication returns immutable `DeviceAuthInfo` data (including `name`) rather than an ORM entity; no ORM object crosses a session boundary.
- The handler's `get_session()` is transaction-neutral: it rolls back on exceptions and always closes, but never auto-commits. A handler explicitly owns its business transaction with `session.begin()`.
- Successful authentication schedules `_update_presence()`, which opens, commits/rolls back, and closes its own `SessionLocal`; failed authentication never schedules a presence update.
- SQLAlchemy autobegin starts a transaction on the first SELECT. Isolating the auth SELECT prevents that implicit transaction from occupying the handler session and allows the handler to open its own explicit transaction without `InvalidRequestError`.
- Regression coverage verifies the dataclass fields, clean handler `session.begin()`, no checked-out connection after a TestClient response, successful/failed presence behavior, and the presence task's independent session.

## P6 — Cashier payments dan balance-check

- Timestamp menggunakan Unix epoch seconds dan toleransi ±300 detik; di luar rentang menghasilkan HTTP 400 `CLOCK_SKEW`. Pesan Indonesia untuk celah Section 14.14: **"Jam perangkat tidak sinkron. Hubungi admin."**
- PIN salah pada `POST /api/v1/balance-check` menambah counter `cards.pin_fail_count` yang sama dengan pembayaran. PIN, kartu, dan risiko penyalahgunaan sama sehingga percobaan tidak dapat di-reset dengan berpindah endpoint.
- Counter PIN gagal disimpan dan di-commit dalam transaksi independen agar bertahan ketika request bisnis gagal. Percobaan ketiga mengubah kartu menjadi LOCKED dan menghasilkan `CARD_LOCKED`; PIN benar mereset counter dalam transaksi utama.
- SELECT card/member dan idempotency dilakukan sebelum transaksi penulisan. Session di-rollback untuk menutup SQLAlchemy autobegin sebelum `session.begin()`, sesuai session transaction-neutral P5.
- Idempotency membandingkan member, card, device, PAYMENT/DEBIT, ONLINE, amount, dan actor. Waktu server tidak dibandingkan karena retry identik terjadi pada waktu berbeda; response menggemakan row asli.
- Balance-check tidak menulis ledger; audit `balance_check` disimpan dalam transaksi independen dengan actor DEVICE, device id, member id, IP, serta before/after null.
- GET transaction menyamarkan transaksi hilang dan transaksi lintas device sebagai HTTP 404 dengan pesan sama.
- HTTP status P6: 200 sukses dan duplicate identik; 400 CLOCK_SKEW/VALIDATION_ERROR; 401 device auth; 404 transaksi hilang/lintas device; 409 duplicate UUID payload berbeda; 422 saldo tidak cukup, PIN salah, kartu terkunci/tidak aktif/tidak dikenal, atau member suspended.
- Logging memakai JSON formatter dan filter tanpa dependency eksternal. Filter menyamarkan PIN, Authorization/Bearer, nilai X-Device-Id, UID (hanya empat karakter terakhir), dan NIK. Secret tidak boleh dimasukkan ke pesan log.
- Adaptasi struktur: Card berada di `app.models.member` tanpa ORM relationship `member`; service mengambil Member melalui `card.member_id`. DomainError P5 tetap kompatibel dengan positional message lama sambil menambahkan code, status_code, message_format, details, dan rendered_message.


## P7 — Cashier top-up
- PIN operator menggunakan Argon2id dengan parameter default argon2-cffi yang sama dengan primitive P3; modul terpisah `security/operator_pin.py` disiapkan untuk dipakai P14.
- Lima kegagalan PIN operator mengunci operator selama 15 menit; counter kegagalan di-commit pada transaksi independen agar tidak hilang ketika transaksi top-up ditolak.
- Operator harus memiliki relasi `operator_devices` ke Cashier pemanggil. Device Vending ditolak sebelum validasi kartu.
- Migration 0002 sempat memperluas sumber ledger untuk transaksi TOPUP CASHIER; penyimpangan ini dikoreksi oleh migration 0004 agar kembali mengikuti Section 5.
- Request UUID disimpan pada `topup_requests.request_uuid` dan ledger `transactions.txn_uuid`; kedua tabel memiliki unique constraint masing-masing.

- CI final P7 (commit `370d8eedcd495fe3c899b33c1e2b3785e11dd875`): Ruff check + format SUCCESS; Pytest 132 passed; coverage seluruh package app 90,38% (1.310 statements, 126 missed). Tidak ada WebSocket atau Admin WebUI pada P7.


## P8 — Admin top-up service layer
- Top-up admin menggunakan `topup_requests.source=WEBUI` sesuai Section 5; migration 0003 sempat menambahkan ADMIN dan dikoreksi oleh migration 0004.
- `LedgerService._reverse_internal()` adalah primitive komposisional tanpa commit dan wajib dipanggil dalam transaksi aktif; public `reverse()` tetap membuka transaksi sendiri lalu mendelegasikan ke primitive tersebut.
- AdminTopupService menerima `performed_by_admin_id` dan IP dari caller; service tidak mengelola request/session WebUI, sehingga dapat dipakai kelak oleh handler P14 tanpa coupling HTTP.
- Reversal top-up hanya dilakukan jika saldo saat ini masih mencukupi seluruh nominal; jika tidak, domain mengembalikan REVERSE_INSUFFICIENT dengan pesan untuk memakai Koreksi Saldo setelah verifikasi.

- CI final P8 (commit `e2509927de86ac37762842675e7b746b55a52dd4`): Ruff check + format SUCCESS; Pytest 142 passed; total coverage 90,36%. P8 menambahkan 10 test case dibanding P7.


## P9 — Allowance cache and event hook
- Per-device cache membership is computed from completed PAYMENT rows: top 100 by count on that device in the last 60 days, ties by most recent payment, then global recent-payment fill. Eligibility requires ACTIVE member and ACTIVE card.
- N is the number of active offline-capable device caches that include the member. Each included device gets `min(offline_card_cap, floor(balance/N))`; this keeps the allowance sum bounded by the balance.
- `offline_hold_mode=soft` preserves full online spendability. `hard` reserves `sum(offline_allowances.amount)`; PaymentService and AdminTopupService.reverse_topup enforce the resulting spendable balance before debiting.
- CacheUpdateEvent is queued in `session.info["mgt_pending_events"]`; SQLAlchemy `Session.after_commit` publishes it through the in-process EventBus. `Session.after_rollback` clears the queue to prevent stale events if a session is reused. P10 may add a WS subscriber; none is included in P9.

- CI final P9 (commit `c2066b970db9317fcd97c8088da4cda5b34d41aa`): Ruff check + format SUCCESS; Pytest 151 passed; total coverage 90,69%. Regression tests P4/P6 were updated to seed the active card and completed-payment history required by the new cache eligibility predicate. `test_allowance_sum_never_exceeds_balance` passed.

## P7–P9 enum alignment
- transactions.source must remain ONLINE|OFFLINE_SYNC|ADMIN per Section 5. Cashier topup is distinguished by topup_requests.source=CASHIER, not by transactions.source. Admin/WebUI topup uses topup_requests.source=WEBUI. The ADMIN/CASHIER source additions in migrations 0002/0003 were reverted in 0004.
