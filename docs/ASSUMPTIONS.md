# Asumsi Implementasi

> Every time the spec is ambiguous, choose the simplest safe option, record it here, and continue. Do not stop to ask.

## Catatan asumsi
- Setiap keputusan tambahan dicatat di bawah fase terkait.

## P1.5

- app/config.py sudah memiliki default untuk seluruh setting yang digunakan; .env.test tidak diperlukan.
- Menambahkan python-dotenv karena Pydantic Settings membaca env_file=".env".
- Ruff import grouping diperbaiki secara minimal pada alembic/env.py, app/db.py, dan app/main.py; logika tidak berubah.
- ruff format --check lulus tanpa perubahan format tambahan.
- Workflow CI menggunakan DATA_KEY Base64 dummy yang tervalidasi menjadi 32 byte; tidak ada secret produksi.
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
- CI pada commit schema menunjukkan 7 tes lulus dan satu deprecation warning dari integrasi Starlette TestClient/httpx; tidak memengaruhi hasil pengujian.
