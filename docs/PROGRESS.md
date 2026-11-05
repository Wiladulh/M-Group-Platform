# Progress Proyek

| Step | Description | Status | Commit |
|---|---|---|---|
| P1.5 | CI setup: Ruff + pytest config, minimal health/import tests, GitHub Actions workflow (lint + test jobs both green) | DONE | 2854c7a2b9fc9f7034e0bb1b01234a682c7063f0 |
| P0 | Membaca spesifikasi baseline v1.3 dan membuat dokumentasi pemahaman serta scaffolding docs | Selesai | 06bcf7428cc54beeeb13c3b6abe21b3a1d28ffe9 |
| P1 | Server skeleton: packaging, settings, SQLite engine, FastAPI health endpoint, dan Alembic environment | DONE | 766145683b6025a4b4cad756cf8fd41e00a199b6 |
| P2 | Full database schema + migration: 19 SQLAlchemy models, Alembic revision 0001, constraints/indexes, schema tests dan DB_SCHEMA.md | DONE | 31405495385b7f3aa792ece0b036a0015d8d3eed |
| P3 | Security primitives (Argon2id, PIN, encryption, token, CSRF) | DONE | b86e533bced8dd0ae09f036333bf901f79fd6d31 |
| P4 | Ledger service, atomic debit/credit, allowance MVP, verify-ledger CLI, dan concurrency tests | DONE | e9205b8bfd909a3045751373794f9045ba2daa96 |
| Berikutnya | Fase server lanjutan, transaksi API (P6), WebSocket/binding/offline sync, lalu WebUI dan firmware sesuai prompt fase berikutnya | Belum dimulai | — |

## Catatan

- P0 hanya membuat dokumentasi; belum ada kode aplikasi, firmware, migrasi, atau konfigurasi runtime.
- P1 hanya menyediakan skeleton. Tidak ada model, router, service, tabel, migration revision, atau firmware.
- Engine SQLite mengaktifkan WAL, foreign keys, dan busy timeout 5000 ms pada setiap koneksi.
- Alembic telah dikonfigurasi ke settings dan Base metadata, tetapi belum memiliki revision/head karena pembuatan migration dilarang pada P1. Perintah `alembic upgrade head` baru dapat dijalankan setelah migration schema pertama dibuat pada fase berikutnya.
- Kriteria runtime (install, health endpoint, Alembic dengan revision, dan Ruff) harus diverifikasi lokal; tidak diklaim telah dijalankan dalam sesi ini.
- Status fase berikutnya hanya boleh diubah setelah acceptance criteria yang relevan pada Section 16 lulus.
- Setelah setiap fase, catat ringkasan pekerjaan, hasil tes/build, asumsi baru, dan commit yang memuat hasilnya.

## Catatan P1.5

- Commit implementasi CI dengan kedua job green: `2854c7a2b9fc9f7034e0bb1b01234a682c7063f0`.
- GitHub Actions run: [CI run 41759283719](https://github.com/Wiladulh/M-Group-Platform/actions/runs/41759283719).
- Job `Ruff`: success, durasi 16 detik (02:13:30–02:13:46 UTC).
- Job `Pytest`: success, durasi 17 detik (02:13:30–02:13:47 UTC).
- Pytest menjalankan dua tes: health endpoint dan smoke test import seluruh modul di `app/`.
- Catatan deviasi dan penyesuaian P1.5 tercantum pada bagian P1.5 di `ASSUMPTIONS.md`.

## Catatan P2

- Implementasi schema/model dan migration revision 0001: commit `31405495385b7f3aa792ece0b036a0015d8d3eed`.
- Green CI run untuk commit tersebut: [CI run 41762822003](https://github.com/Wiladulh/M-Group-Platform/actions/runs/41762822003).
- Job `Pytest`: SUCCESS, 22 detik; job `Ruff`: SUCCESS, 19 detik.
- `server/tests/test_schema.py`: 5 pengujian lulus (upgrade, downgrade, saldo negatif, partial unique kartu aktif/terkunci, dan amount transaksi positif). Total suite CI: 7 passed, 1 warning dari deprecation Starlette TestClient/httpx.
- Migration membentuk 19 tabel dan 7 indeks eksplisit, termasuk partial unique index kartu ACTIVE/LOCKED.
- SQLite pragmas pada engine aplikasi diverifikasi: foreign_keys=ON, busy_timeout=5000, journal_mode=WAL per koneksi.
- P2 ini hanya menyelesaikan schema dan migration. Router, service, device auth, ledger business logic, dan allowance logic belum dibuat; itu tetap berada pada fase berikutnya.


## Catatan P3
- Security primitives dan pengujian selesai pada commit `b86e533bced8dd0ae09f036333bf901f79fd6d31`.
- P3 adalah implementasi security primitives; baris roadmap lama yang menyebut P3 sebagai WebSocket telah dikoreksi.

## Catatan P4 — DONE
- Ledger service, allowance MVP, CLI verify-ledger, dan test suite P4 sudah ditambahkan ke branch `main`.
- Commit implementasi P4: `e9205b8bfd909a3045751373794f9045ba2daa96`.
- Pengujian concurrency menggunakan 10 thread pada file-backed SQLite, WAL, busy_timeout 30 detik, dan transaksi `BEGIN IMMEDIATE`; hasil final: 5 berhasil, 5 ditolak, saldo akhir 0.
- P4 selesai: kedua job CI (Ruff dan Pytest) sukses pada workflow run 116; 71 tes lulus termasuk concurrency test 10 thread.

- CI P4: https://github.com/Wiladulh/M-Group-Platform/actions/runs/41959352025 (Ruff SUCCESS, Pytest SUCCESS; 71 passed).
