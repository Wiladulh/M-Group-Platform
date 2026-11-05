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
- Index cards.uid dan members.nik_idx dibuat eksplisit.
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
- Session dependency request-scoped melakukan commit setelah request sukses, rollback saat exception, dan selalu close; dependency yang sama dipakai oleh auth dan handler endpoint.
- Kegagalan auth tidak mengubah last_seen_at/last_ip; presence hanya diperbarui setelah status ACTIVE dan token terverifikasi.
- CI final P5 pada run 42026075969: Ruff SUCCESS, Pytest SUCCESS (82 passed, 1 warning, security coverage 96.30%).


## P3 patch — reject all-zero DATA_KEY
- Settings.data_key dan _load_fernet_key() sama-sama menolak key Base64 yang mendekode menjadi 32 byte nol; key wajib berisi setidaknya satu byte non-zero.
- Regression tests mencakup validator Settings, loader Fernet, key acak 32 byte, dan key acak per-session pytest.

## Coverage patch — measure the complete app package
- Pytest coverage scope diperluas dari `app/security` menjadi seluruh package `app` (`--cov=app`); threshold tetap 70% dan tidak ada module yang dikecualikan.
- Baseline sebelum perubahan ini: P5 CI hanya mengukur `app/security` (96.30% pada run 42026075969); angka tersebut bukan baseline coverage seluruh aplikasi.
- Hasil CI scope seluruh `app`: **89.00%** (873 statements, 96 missed), 86 tests passed. Tidak ada module di bawah 70%; terendah `app/services/settings.py` 73% (37 statements), lalu `app/services/ledger.py` 75% (126), `app/services/allowance.py` 75% (56), dan `app/cli.py` 72% (82).
