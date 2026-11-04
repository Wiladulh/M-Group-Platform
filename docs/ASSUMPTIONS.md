# Asumsi Implementasi

> Every time the spec is ambiguous, choose the simplest safe option, record it here, and continue. Do not stop to ask.

## Catatan asumsi
- Belum ada asumsi implementasi yang diterapkan. Setiap keputusan tambahan akan dicatat dengan tanggal, konteks, pilihan yang diambil, alasan keamanan/kesederhanaan, serta dampaknya.

## P1.5

- `app/config.py` sudah memiliki default untuk seluruh setting yang digunakan pada fase ini; karena itu `.env.test` tidak diperlukan dan tidak dibuat.
- Menambahkan dependency runtime `python-dotenv` ke `server/pyproject.toml` karena Pydantic Settings membaca `env_file=".env"`; tanpa dependency ini dukungan file dotenv tidak terpasang secara eksplisit.
- Ruff menemukan import yang tidak terurut pada `server/alembic/env.py`, `server/app/db.py`, dan `server/app/main.py`. Hanya pengelompokan/spacing import yang disesuaikan; tidak ada perubahan logika aplikasi.
- `ruff format --check .` lulus tanpa perlu perubahan format tambahan.
- Workflow CI menggunakan `DATA_KEY` Base64 dummy yang tervalidasi menjadi 32 byte, menggantikan contoh nilai hexadecimal yang tidak sesuai dengan validator `app/config.py`. Tidak ada secret produksi yang digunakan.
- Root `.gitignore` sebelumnya tidak ada; dibuat dengan pola ignore yang diminta. `server/.gitignore` yang sudah ada dipertahankan.
