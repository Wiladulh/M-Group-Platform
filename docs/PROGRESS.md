# Progress Proyek

| Step | Description | Status | Commit |
|---|---|---|---|
| P1.5 | CI setup: Ruff + pytest config, minimal health/import tests, GitHub Actions workflow (lint + test jobs both green) | DONE | 2854c7a2b9fc9f7034e0bb1b01234a682c7063f0 |
| P0 | Membaca spesifikasi baseline v1.3 dan membuat dokumentasi pemahaman serta scaffolding docs | Selesai | 06bcf7428cc54beeeb13c3b6abe21b3a1d28ffe9 |
| P1 | Server skeleton: packaging, settings, SQLite engine, FastAPI health endpoint, dan Alembic environment | DONE | 766145683b6025a4b4cad756cf8fd41e00a199b6 |
| P2 | Full database schema + migration: 19 SQLAlchemy models, Alembic revision 0001, constraints/indexes, schema tests dan DB_SCHEMA.md | DONE | 31405495385b7f3aa792ece0b036a0015d8d3eed |
| P3 | Security primitives (Argon2id, PIN, encryption, token, CSRF) | DONE | b86e533bced8dd0ae09f036333bf901f79fd6d31 |
| P4 | Ledger service, atomic debit/credit, allowance MVP, verify-ledger CLI, dan concurrency tests | DONE | e9205b8bfd909a3045751373794f9045ba2daa96 |
| P5 | Request-scoped DB session, device bearer auth, GET device config, settings service, seed-minimal CLI, tests dan dokumentasi | IMPLEMENTED — CI pending | pending |

## Catatan
- P0 hanya membuat dokumentasi; belum ada kode aplikasi, firmware, migrasi, atau konfigurasi runtime.
- P1 hanya menyediakan skeleton. Tidak ada model, router, service, tabel, migration revision, atau firmware.
- Engine SQLite mengaktifkan WAL, foreign keys, dan busy timeout 5000 ms pada setiap koneksi.
- Alembic telah dikonfigurasi ke settings dan Base metadata; migration schema 0001 ditambahkan pada P2.
- Status fase hanya boleh diubah menjadi DONE setelah acceptance criteria Section 16 dan kedua job CI lulus.
- Setelah setiap fase, catat ringkasan pekerjaan, hasil tes/build, asumsi baru, dan commit yang memuat hasilnya.

## Catatan P1.5
- Commit CI: `2854c7a2b9fc9f7034e0bb1b01234a682c7063f0`.
- GitHub Actions: [CI run 41759283719](https://github.com/Wiladulh/M-Group-Platform/actions/runs/41759283719); Ruff dan Pytest SUCCESS.

## Catatan P2
- Schema dan migration revision 0001: commit `31405495385b7f3aa792ece0b036a0015d8d3eed`.
- CI: [run 41762822003](https://github.com/Wiladulh/M-Group-Platform/actions/runs/41762822003); Ruff dan Pytest SUCCESS.
- Migration membentuk 19 tabel dan 7 indeks eksplisit; SQLite pragmas diverifikasi.

## Catatan P3
- Security primitives selesai pada commit `b86e533bced8dd0ae09f036333bf901f79fd6d31`.

## Catatan P4
- Ledger service, allowance MVP, CLI verify-ledger, dan concurrency tests selesai pada commit `e9205b8bfd909a3045751373794f9045ba2daa96`.
- CI P4: [run 41959352025](https://github.com/Wiladulh/M-Group-Platform/actions/runs/41959352025); Ruff SUCCESS, Pytest SUCCESS, 71 passed.

## Catatan P5
- Implementasi P5 dikerjakan pada branch `p5-device-auth` dalam tiga logical commits.
- Seed membuat satu Admin (Argon2id, must_change_password=true) dan tiga perangkat development. Device Key ditampilkan satu kali saat perangkat baru dibuat; nilai database berupa SHA-256 hash.
- Tidak ada migration baru karena tabel dan kolom yang diperlukan telah tersedia dari schema P2.
- Hasil CI akan dicatat setelah workflow Ruff dan Pytest selesai.
