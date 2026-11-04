# Progress Proyek

| Step | Description | Status | Commit |
|---|---|---|---|
| P1.5 | CI setup: Ruff + pytest config, minimal health/import tests, GitHub Actions workflow (lint + test jobs both green) | DONE | 2854c7a2b9fc9f7034e0bb1b01234a682c7063f0 |
| P0 | Membaca spesifikasi baseline v1.3 dan membuat dokumentasi pemahaman serta scaffolding docs | Selesai | 06bcf7428cc54beeeb13c3b6abe21b3a1d28ffe9 |
| P1 | Server skeleton: packaging, settings, SQLite engine, FastAPI health endpoint, dan Alembic environment | DONE | 766145683b6025a4b4cad756cf8fd41e00a199b6 |
| P2 | Server core, database schema, device auth, ledger, dan allowance | Belum dimulai | — |
| P3 | WebSocket, remote binding, dan offline sync | Belum dimulai | — |
| P4 | Admin WebUI (tahap 3a dan 3b sesuai Section 18) | Belum dimulai | — |
| P5 | firmware-common dan native tests | Belum dimulai | — |
| P6 | Cashier Firmware | Belum dimulai | — |
| P7 | Vending Firmware | Belum dimulai | — |
| P8 | Simulator, dokumentasi lanjutan, dan hardening | Belum dimulai | — |

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
- GitHub Actions run: [CI #5](https://github.com/Wiladulh/M-Group-Platform/actions/runs/41759283719).
- Job `Ruff`: success, durasi 16 detik (02:13:30–02:13:46 UTC).
- Job `Pytest`: success, durasi 17 detik (02:13:30–02:13:47 UTC).
- Pytest menjalankan dua tes: health endpoint dan smoke test import seluruh modul di `app/`.
- Catatan deviasi dan penyesuaian P1.5 tercantum pada bagian P1.5 di `ASSUMPTIONS.md`.
