# Pemahaman Proyek M-Group Platform

## A. Ringkasan arsitektur (10 baris)
1. M-Group Platform adalah sistem server-centric dan offline-first untuk pembayaran anggota melalui unit Cashier dan Vending.
2. Server menjadi sumber kebenaran saldo; saldo melekat pada Member UID, bukan pada kartu NFC.
3. Identitas anggota adalah Member UID permanen; Card UID adalah identitas kartu fisik yang dapat diganti.
4. Backend menggunakan Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, dan SQLite WAL.
5. Ledger transaksi bersifat append-only, idempotent, dan seluruh nominal Rupiah disimpan sebagai integer.
6. WebUI admin dirender server-side dengan Jinja2, HTMX, Alpine.js, dan Tailwind standalone tanpa CDN.
7. Cashier ESP32-WROOM-32 dan Vending ESP32-S3 berkomunikasi dengan server melalui REST dan WebSocket.
8. Firmware-common menyediakan logika jaringan, cache anggota, verifikasi PIN offline, antrean transaksi, provisioning, keypad, dan LED.
9. Saat offline, perangkat memakai cache terenkripsi dan allowance terbatas; sinkronisasi server tidak boleh membuat saldo anggota negatif.
10. Pengerjaan wajib mengikuti urutan fase pada Section 18 dan baru dinyatakan selesai setelah kriteria penerimaan Section 16 lulus.

## B. 15 keputusan paling kritis dari Section 17 (Decision Log)
1. **Offline capability:** Cashier mode manual dan Vending mendukung Pay serta Check Balance offline; Top-up, Binding, dan PIN Reset hanya online.
2. **Kepemilikan saldo:** Saldo per anggota; satu anggota hanya memiliki satu kartu aktif pada satu waktu.
3. **Jalur Top-up:** Top-up dilakukan melalui WebUI admin atau Cashier dengan Operator Code dan PIN enam digit.
4. **Golden Balance Rule:** Saldo tidak boleh negatif. Transaksi offline yang tidak ter-cover saat sinkronisasi ditolak dan masuk Shortfall/Loss.
5. **Batas offline:** Maksimum Rp30.000 per transaksi, allowance maksimum Rp50.000 per kartu per unit, jendela 24 jam, dan antrean maksimum 500.
6. **Fund-hold:** Mode bawaan adalah `soft`; mode `hard` tersedia untuk menahan dana sebesar total allowance.
7. **Cache anggota:** Setiap unit menyimpan hingga 100 anggota berdasarkan aktivitas transaksi 60 hari terakhir.
8. **Perlindungan cache/PIN offline:** Verifier offline terpisah menggunakan PBKDF2; cache dienkripsi dengan AES-GCM.
9. **Protokol perangkat:** REST + WebSocket dengan token autentikasi per perangkat; MQTT tidak digunakan.
10. **Hardware Cashier:** ESP32-WROOM-32; keypad Col3 GPIO17 dan Col4 GPIO16; GPIO34 tidak digunakan; LED GPIO13; buzzer GPIO14 opsional.
11. **Hardware Vending:** ESP32-S3 N16R8, TFT ILI9341, lima servo SG90 positional; home 0°, dispense 90° searah jarum jam, hold 700 ms; satu siklus untuk satu produk; LED GPIO46; tanpa buzzer/sensor jatuh.
12. **Platform firmware:** Arduino + PlatformIO; OTA tidak termasuk v1.3.
13. **Teknologi WebUI:** Jinja2 + HTMX + Alpine.js + Tailwind standalone CLI; tidak menggunakan CDN.
14. **Penanganan dispense gagal:** Kegagalan dispense menghasilkan refund penuh otomatis.
15. **Konektivitas dan UX operasional:** LED hijau solid berarti online, kedip cepat offline, kedip lambat provisioning; heartbeat 10 detik dan escalation ladder reconnect hingga restart 10 menit.

Keputusan lain pada Decision Log (16–35) tetap mengikat, termasuk batas scope v1.3, satu akun Admin, struktur menu WebUI, topup_requests, NIK terenkripsi, remote binding melalui Cashier, Setup Code, Device Key, format laporan, dan satu produk per transaksi.

## C. 10 bagian ambigu atau belum cukup spesifik
1. **Konflik NIK “diisi sekali” vs edit anggota:** Section 4.4 dan Decision 35 menyatakan NIK diisi sekali, tetapi Section 14.7 menyediakan edit NIK. Belum ditegaskan apakah perubahan NIK diizinkan, memerlukan verifikasi tambahan, atau hanya koreksi administratif.
2. **Data pribadi yang disimpan:** Decision 25 menyebut NIK, nama, dan telepon wajib saat registrasi tetapi hanya NIK disimpan; schema tetap memuat full_name dan phone. Makna “hanya NIK disimpan” perlu ditafsirkan sebagai hanya NIK sensitif yang dienkripsi, bukan menghapus nama/telepon.
3. **Semantik ledger untuk status non-final:** Ledger disebut append-only dengan hanya kolom status boleh berubah, sementara acceptance criteria mensyaratkan invariant saldo = kredit - debit. Belum dijelaskan secara formal apakah baris REJECTED, PENDING_DISPENSE, DISPENSE_FAILED, dan REVERSED ikut dihitung atau bagaimana refund/reversal memengaruhi agregasi.
4. **Idempotency key untuk transaksi server/admin:** Device membuat txn_uuid; transaksi source ADMIN juga memiliki txn_uuid yang dibuat server. Algoritme pembuatan, cakupan unik, retensi, dan respons untuk key sama dengan payload berbeda belum dirinci.
5. **Sinkronisasi jam offline:** Validitas clock dapat berasal dari NTP sejak boot atau RTC/NVS, tetapi toleransi drift, penyimpanan last-known-good time, dan perlakuan setelah kehilangan daya panjang belum didefinisikan.
6. **Allowance saat jumlah unit berubah:** Formula allowance membagi saldo dengan jumlah unit offline-capable yang meng-cache anggota. Belum dijelaskan kapan unit dianggap masuk/keluar dari denominator, bagaimana unit lama yang offline ditangani, dan bagaimana versi allowance mencegah update terlambat menimpa data baru.
7. **Transisi soft/hard fund-hold:** Perilaku ketika Admin mengganti mode saat perangkat offline atau ketika allowance yang sudah diterbitkan belum diterima unit tidak dijelaskan secara lengkap.
8. **Kontrak WebSocket dan ACK:** Envelope, daftar tipe pesan, dan batas ACK lima detik tersedia, tetapi format ACK/error, retry, deduplikasi command, ordering, dan perilaku reconnect untuk command yang belum di-ACK belum ditentukan.
9. **Definisi operasional status online/busy:** Online didefinisikan dengan WS dan ping, sementara pemilihan Cashier juga memerlukan status busy. Payload status ada, tetapi state machine lengkap, timeout, dan kondisi race saat Scan dimulai belum dirinci.
10. **Kebijakan database dan deployment awal:** SQLite WAL, Docker, dan opsi Uvicorn langsung ditetapkan, tetapi backup/restore consistency, lokasi volume persisten, migrasi saat startup, strategi lock/concurrency, dan konfigurasi reverse proxy/TLS belum dijabarkan sampai level operasional.

Catatan: daftar ini mencatat pertanyaan desain untuk ditangani melalui keputusan paling sederhana dan aman pada implementasi; bukan alasan untuk menghentikan pekerjaan.

## D. Checklist usulan langkah implementasi pertama — Server Skeleton
- [ ] Baca kembali `docs/README.md`, `docs/UNDERSTANDING.md`, `docs/ASSUMPTIONS.md`, `docs/PROGRESS.md`, serta spesifikasi baseline sebelum memulai fase.
- [ ] Pastikan branch target adalah `main` dan baseline `m-group-platform-spec.md` tidak berubah.
- [ ] Buat struktur `/server` sesuai Section 2 tanpa membuat modul di luar urutan fase.
- [ ] Siapkan `pyproject.toml` dengan Python >=3.11, FastAPI, Uvicorn, SQLAlchemy 2.x, Alembic, Pydantic v2, dan tool kualitas yang ditetapkan.
- [ ] Siapkan konfigurasi berbasis environment, validasi konfigurasi wajib, dan `.env.example` tanpa secret nyata.
- [ ] Buat aplikasi FastAPI minimal dengan lifecycle yang jelas dan endpoint publik `GET /healthz` yang mengembalikan hanya `{"status":"ok"}`.
- [ ] Siapkan koneksi SQLite dengan WAL, foreign keys ON, dan busy_timeout 5000; jangan menambahkan model/domain yang belum masuk fase.
- [ ] Inisialisasi Alembic agar migrasi dapat dijalankan dari database kosong.
- [ ] Siapkan logging JSON terstruktur dengan redaksi untuk PIN, token, dan NIK.
- [ ] Siapkan Dockerfile dan docker-compose sesuai stack; pastikan database/media memakai volume persisten.
- [ ] Tambahkan tes skeleton untuk health endpoint, startup, konfigurasi, dan migrasi database kosong.
- [ ] Jalankan pytest dan ruff; perbaiki seluruh kegagalan sebelum menyatakan skeleton lulus.
- [ ] Catat hasil, perintah uji, commit, dan asumsi baru pada `docs/PROGRESS.md`.
- [ ] Jangan mulai fitur ledger, autentikasi perangkat, WebSocket, WebUI, atau firmware sebelum skeleton dan gerbang fase terkait disetujui/lulus.

---
Dokumen ini merupakan interpretasi awal spesifikasi v1.3. Jika terjadi perbedaan, `m-group-platform-spec.md` tetap menjadi sumber kebenaran tunggal.
