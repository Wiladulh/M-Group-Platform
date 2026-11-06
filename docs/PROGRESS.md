# Progress Proyek

| Step | Description | Status | Commit |
|---|---|---|---|
| P1.5 | CI setup: Ruff + pytest config, minimal health/import tests, GitHub Actions workflow (lint + test jobs both green) | DONE | 2854c7a2b9fc9f7034e0bb1b01234a682c7063f0 |
| P0 | Membaca spesifikasi baseline v1.3 dan membuat dokumentasi pemahaman serta scaffolding docs | Selesai | 06bcf7428cc54beeeb13c3b6abe21b3a1d28ffe9 |
| P1 | Server skeleton: packaging, settings, SQLite engine, Alembic environment, FastAPI health endpoint | DONE | 766145683b6025a4b4cad756cf8fd41e00a199b6 |
| P2 | Full database schema + migration: 19 SQLAlchemy models, Alembic revision 0001, constraints/indexes, schema tests dan DB_SCHEMA.md | DONE | 31405495385b7f3aa792ece0b036a0015d8d3eed |
| P3 | Security primitives (Argon2id, PIN, encryption, token, CSRF) | DONE | b86e533bced8dd0ae09f036333bf901f79fd6d31 |
| P4 | Ledger service, atomic debit/credit, allowance MVP, verify-ledger CLI, dan concurrency tests | DONE | e9205b8bfd909a3045751373794f9045ba2daa96 |
| P5 | Request-scoped DB session, device bearer auth, GET device config, settings service, seed-minimal CLI, tests dan dokumentasi | DONE | f16d34a3e069bcf01d63f6b675ed9fadb538f31b |
| P6 | Cashier payment, balance-check, transaction lookup, PIN failure/lockout, idempotency, audit, dan redacted structured logging | DONE | 46018b8e0f372cc13b61814abdd41709fd32bcfc |
| P7 | Cashier top-up endpoint, operator PIN lockout/binding, ledger credit, idempotency, audit, allowance refresh | DONE | 370d8eedcd495fe3c899b33c1e2b3785e11dd875 |

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

## Catatan P5 — implementasi awal
- Implementasi P5 awal dan seed CLI tercatat pada commit `f16d34a3e069bcf01d63f6b675ed9fadb538f31b`.
- CI awal P5: [run 42026075969](https://github.com/Wiladulh/M-Group-Platform/actions/runs/42026075969); Ruff SUCCESS, Pytest SUCCESS (82 passed).

## Pre-P6 patch batch — P3, coverage, P4, P5
- P3 DATA_KEY: validator dan Fernet loader menolak key 32-byte seluruhnya nol; empat regression tests ditambahkan.
- Coverage: cakupan pytest menjadi seluruh package `app`, threshold 70%; hasil setelah P4 **89,44%** (881 statements, 93 missed), 90 tests passed, tanpa modul di bawah 70%.
- P4 ledger: `_debit_internal()` dan `_credit_internal()` mewajibkan transaksi aktif dan tidak melakukan commit/rollback; public methods mempertahankan transaksi mandiri.
- P5 auth: autentikasi memakai session SELECT terisolasi dan mengembalikan `DeviceAuthInfo`; handler session tidak auto-commit; presence task memakai session mandiri.
- Regression tests P5 mencakup info dataclass, transaksi handler `session.begin()`, lifecycle pool, presence sukses/gagal, dan session independen untuk task.
- Commit PATCH 4 (auth/session/handler/tests/docs) tercatat di riwayat `main`.
- CI P5 patch batch: [run 42157790994](https://github.com/Wiladulh/M-Group-Platform/actions/runs/42157790994); Ruff SUCCESS, Pytest SUCCESS (**94 passed**, 1 warning), total coverage **89,06%** (905 statements, 99 missed).
- Regression test handler membuktikan `with session.begin(): session.execute(text("SELECT 1"))` berhasil tanpa `InvalidRequestError`.

## P6 — Cashier payments dan balance-check
- Implementasi P6: commit `46018b8e0f372cc13b61814abdd41709fd32bcfc`.
- Endpoint: `POST /api/v1/payments`, `POST /api/v1/balance-check`, `GET /api/v1/transactions/{txn_uuid}`; `GET /api/v1/device/config` tetap tersedia.
- CI implementasi P6: [run 42166090180](https://github.com/Wiladulh/M-Group-Platform/actions/runs/42166090180); Ruff SUCCESS, Pytest SUCCESS (**117 passed**), total coverage **90,54%**.
- Annotated tag [v0.1-server-core](https://github.com/Wiladulh/M-Group-Platform/releases/tag/v0.1-server-core) dibuat melalui workflow Tag dan menunjuk tepat ke S1 `6ea4fbe40249cdf76cbc88bc0bb81a8eb70e441e`. Tag tidak dipindahkan.
- Workflow sementara `.github/workflows/format.yml` dan `.github/workflows/tag.yml` telah dihapus setelah digunakan.
- S2 (penghapusan workflow Tag): `a35ecee193e649ce53fff198d0df5069572a9486`; CI [run 42168663044](https://github.com/Wiladulh/M-Group-Platform/actions/runs/42168663044) — Ruff SUCCESS dan Pytest SUCCESS.
- Catatan asumsi/keputusan P6 dicatat di `docs/ASSUMPTIONS.md`.
- Verifikasi manual CLI `verify-ledger` belum diklaim; regression test untuk tiga pembayaran sukses mengharapkan output `OK: 1 members verified`.


## P7 — Cashier top-up
- Implementasi endpoint `POST /api/v1/topups`, validasi kartu/member/operator, lockout PIN operator, idempotency, ledger credit atomik, audit log, dan allowance refresh.
- Migration 0002 memperbolehkan source CASHIER pada ledger.
- CI P7: [run 42207631202](https://github.com/Wiladulh/M-Group-Platform/actions/runs/42207631202); Ruff SUCCESS, Pytest SUCCESS (**132 passed**), total coverage **90,38%**.
- Dibanding baseline P6 (117 tests), P7 menambahkan **15 test case efektif** termasuk parameterisasi amount min/max.
