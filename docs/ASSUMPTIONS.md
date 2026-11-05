# Asumsi Implementasi

> Every time the spec is ambiguous, choose the simplest safe option, record it here, and continue. Do not stop to ask.

## Catatan asumsi
- Setiap keputusan tambahan dicatat di bawah fase terkait.

## P1.5
- app/config.py sudah memiliki default untuk seluruh setting yang digunakan; .env.test tidak diperlukan.
- Menambahkan python-dotenv karena Pydantic Settings membaca env_file=".env".
- Ruff import grouping diperbaiki secara minimal pada alembic/env.py, app/db.py, dan app/main.py; logika tidak berubah.
- ruff format --check lulus tanpa perubahan format tambahan.
- CI tidak menyimpan DATA_KEY produksi; key pengujian harus dibuat secara acak per proses.
- Root .gitignore dibuat; server/.gitignore dipertahankan.

## P2
- Enum/status disimpan sebagai String dengan CHECK constraints agar validasi ditegakkan SQLite dan tidak bergantung pada validasi aplikasi.
- JSON payload disimpan sebagai TEXT; encoding/decoding menjadi tanggung jawab lapisan aplikasi.
- DateTime(timezone=True) digunakan untuk timestamp. SQLite tidak memiliki tipe timestamp dengan timezone native; aplikasi wajib menulis dan membaca nilai sebagai UTC.
- Kolom yang tidak ditandai nullable dibuat NOT NULL; kolom yang dinyatakan nullable/opsional dibuat nullable. Default sederhana seperti status ACTIVE dan counter 0 dipasang bila aman.
- catalog_meta dan admin_users singleton ditegakkan dengan CHECK(id = 1).
- Index cards.uid dan members.nik_idx dibuat eksplisit meskipun kolom UNIQUE, sehingga indeks bernama yang diminta deliverable tersedia.
- Migration test menggunakan koneksi SQLite in-memory yang disuntikkan ke Alembic. SQLite in-memory tidak dapat memakai WAL (pragma menghasilkan mode MEMORY); engine aplikasi tetap mengaktifkan WAL untuk database file. Foreign keys dan busy_timeout tetap aktif pada koneksi test.
- Seluruh tabel menggunakan created_at dan updated_at bertipe DateTime(timezone=True); admin_sessions tetap memiliki last_seen_at, expires_at, dan revoked_at selain timestamp umum.
- AdminUser dan CatalogMeta memakai CHECK(id = 1) untuk membatasi masing-masing tabel menjadi maksimal satu baris.
- Kolom FK menggunakan ON DELETE default RESTRICT (tanpa cascade otomatis), agar histori transaksi/audit tidak terhapus secara tidak sengaja.
- Migration revision 0001 membuat 19 tabel. Tujuh indeks eksplisit mencakup enam pola pencarian wajib dan partial unique index kartu ACTIVE/LOCKED.
- Pytest schema dijalankan pada SQLite in-memory StaticPool dengan foreign_keys=ON dan busy_timeout=5000. SQLite in-memory mengabaikan permintaan WAL dan tetap berada pada mode MEMORY; engine aplikasi file-backed mengaktifkan WAL.
- Pytest schema: lima pengujian khusus; suite CI pada commit schema mencatat 7 passed dan satu deprecation warning dari integrasi Starlette TestClient/httpx.

## P2.1 — DATA_KEY test isolation
- .env.example dan default Settings.data_key menggunakan placeholder invalid agar aplikasi gagal cepat bila developer belum membuat key rahasia.
- tests/conftest.py membuat DATA_KEY URL-safe Base64 dari secrets.token_bytes(32) sekali per sesi pytest; setdefault tetap mengizinkan key eksplisit untuk pengujian khusus.
- Validator Settings menerima alfabet Base64 standar maupun URL-safe, memvalidasi alfabet secara ketat, dan mewajibkan hasil decode tepat 32 byte. Tidak ada key dummy statis pada workflow CI.
## P3 — Security primitives
- Argon2id menggunakan `argon2-cffi PasswordHasher(type=Type.ID)` dengan parameter default pustaka (time_cost=3, memory_cost=65536 KiB, parallelism=4, hash_len=32, salt_len=16). Section 4 menetapkan algoritma Argon2id tetapi tidak menentukan angka parameter, sehingga pemakaian default modern bukan penyimpangan dari spesifikasi.
- `DATA_KEY` dibaca melalui Settings dan divalidasi sebagai Base64 yang mendekode tepat 32 byte; `PIN_PEPPER` merupakan secret independen. Kedua nilai wajib diganti dengan secret produksi dan tidak boleh masuk repository.
- Dependency `argon2-cffi` dan `cryptography` sudah tersedia di dependencies utama; tidak ada perubahan dependency diperlukan.


## P4 — Ledger dan Allowance MVP
- SQLite concurrency test memakai file-backed database dengan WAL, `busy_timeout=30000`, dan SQLAlchemy begin-event yang menjalankan `BEGIN IMMEDIATE`. Ini mencegah deferred read-to-write lock upgrade pada skenario thread bersamaan; saldo tetap dimutasi hanya dengan satu statement atomic `UPDATE ... WHERE balance >= amount RETURNING balance`. Hasil lulus/gagal ditentukan CI, bukan diasumsikan dari konfigurasi.
- Schema v1.3 belum memiliki tabel eksplisit untuk daftar cache member per device. Untuk allowance MVP, denominator N diproksikan sebagai jumlah device berstatus ACTIVE dengan `config_json.offline_enabled=true`. P9 harus menggantinya dengan keanggotaan cache aktual saat pipeline cache tersedia.
- Jika N=0, fungsi mengembalikan mapping kosong (tidak ada device yang menerima allowance); tidak dilakukan pembagian nol dan tidak dibuat baris allowance fiktif.
- Perubahan saldo memicu perhitungan ulang allowance dalam transaksi ledger yang sama. Perangkat yang tidak lagi eligible menerima allowance 0 pada baris lama agar nilai tersimpan tidak tertinggal.
- Reversal tidak mengubah transaksi original; baris ADJUSTMENT baru memakai arah kebalikan dan `ref_txn_id`. Dispense gagal menyimpan status `DISPENSE_FAILED` pada debit awal dan, bila auto-refund aktif, menambahkan baris REFUND CREDIT. Source refund disimpan sebagai `ADMIN` karena CHECK schema hanya mengizinkan ONLINE/OFFLINE_SYNC/ADMIN; pelaku tetap `SYSTEM`.
- CLI menganggap hanya status COMPLETED, PENDING_DISPENSE, DISPENSE_FAILED, dan REVERSED sebagai baris yang memengaruhi invariant; REJECTED tidak mengubah saldo dan tidak dihitung.

- CI validation P4 dijalankan melalui pull request sementara agar status job dan log dapat diperiksa; hasil akhir dicatat setelah Ruff dan Pytest selesai.
