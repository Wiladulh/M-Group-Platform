# Keamanan dan Primitif Kriptografi

Dokumen ini menjelaskan keputusan keamanan server M-Group Platform v1.3. Modul
`server/app/security/` berisi fungsi kriptografi; autentikasi HTTP perangkat kini
diterapkan melalui dependency `require_device`. Admin WebUI/session auth, rate limiting,
lockout, dan otorisasi Admin akan diterapkan pada fase terpisah.

## Hash password Admin dan PIN transaksi

Password Admin dan PIN transaksi disimpan sebagai hash **Argon2id** melalui
`argon2-cffi`. Hash menyertakan salt acak yang dikelola pustaka; jangan membuat salt
sendiri atau menyimpan password/PIN plaintext.

Implementasi memakai `PasswordHasher(type=Type.ID)` dan parameter aman bawaan
`argon2-cffi`:

- varian: Argon2id;
- `time_cost=3`;
- `memory_cost=65536 KiB` (64 MiB);
- `parallelism=4`;
- panjang hash: 32 byte;
- panjang salt: 16 byte.

Parameter dapat ditinjau kembali melalui pengukuran pada server produksi, tetapi
perubahan harus mempertahankan kompatibilitas verifikasi hash lama dan dilakukan
secara eksplisit. Hash Argon2 menyimpan parameter dan salt di dalam string encoded.

Password Admin mengikuti Section 4.1: minimal 10 karakter, mengandung huruf dan angka,
tidak sama dengan username, serta tidak sama dengan password sebelumnya. Helper
`validate_admin_password` melempar `ValueError` dengan pesan Bahasa Indonesia jika
aturan dilanggar.

PIN transaksi wajib tepat 4 digit ASCII dan menolak seluruh repdigit
(`0000` sampai `9999`), `1234`, `4321`, dan `2580`. Sebelum Argon2id, PIN
digabungkan dengan pepper rahasia dari `PIN_PEPPER`. Pepper bukan salt: pepper sama
untuk instalasi server, tidak disimpan bersama hash PIN, dan harus tersedia untuk
memverifikasi PIN. Ganti pepper hanya melalui prosedur migrasi yang dapat menghitung
ulang hash; menggantinya langsung akan membuat seluruh PIN lama tidak dapat diverifikasi.

## Verifier PIN untuk mode offline

Firmware membutuhkan verifier yang dapat dihitung secara konsisten tanpa menjalankan
Argon2id di perangkat. `offline_pin.py` memakai PBKDF2-HMAC-SHA256 dengan:

- iterasi: **20.000**;
- salt acak: **16 byte**;
- derived key: **32 byte**.

Verifier offline berbeda dari hash PIN server. Salt disimpan bersama verifier, bukan
dianggap sebagai rahasia. Perbandingan verifier menggunakan fungsi constant-time.
Verifier ini digunakan dalam cache perangkat yang wajib dienkripsi sesuai keputusan
Section 17; jangan mencatat PIN, verifier, atau cache dalam log.

## Enkripsi NIK dan blind index

NIK dienkripsi menggunakan **Fernet** (authenticated encryption berbasis AES-128-CBC
dan HMAC-SHA256) dari pustaka `cryptography`. Kunci Fernet berasal dari `DATA_KEY`,
yang wajib berupa Base64 standar atau URL-safe yang mendekode menjadi tepat **32 byte
acak**. `_load_fernet_key` memvalidasi encoding dan panjang sebelum digunakan.

Untuk pencarian exact-match, `blind_index_nik` menghitung HMAC-SHA256 dari NIK dengan
32 byte kunci `DATA_KEY`. Indeks bersifat deterministik sehingga NIK yang sama
menghasilkan indeks yang sama, tetapi nilai indeks tidak menyimpan plaintext NIK.
NIK tetap merupakan string bebas sesuai spesifikasi; helper tidak menambahkan
validasi format NIK.

UI harus menampilkan NIK dalam bentuk tersamarkan: empat karakter awal, karakter
tengah diganti bullet, dan empat karakter akhir. Untuk input pendek (delapan karakter
atau kurang), seluruh karakter disamarkan. Penampilan NIK lengkap hanya boleh dilakukan
melalui alur reveal yang diaudit; helper ini sendiri tidak mengatur audit.

## Autentikasi perangkat (Section 4.2)

Setiap unit mengirim dua header pada setiap REST request:

- `Authorization: Bearer <device_token>`
- `X-Device-Id: <device_id>`

Dependency `app.security.device_auth.require_device` mencari device berdasarkan
`X-Device-Id`, memastikan status `ACTIVE`, lalu memverifikasi bearer token dengan
`verify_device_token`. Verifier menghitung SHA-256 token dan membandingkannya dengan
`hmac.compare_digest`; token plaintext tidak pernah dicari atau disimpan di database.

Kegagalan header, format Bearer, ID, token, atau status perangkat selalu menghasilkan
HTTP 401 dengan kode `DEVICE_REVOKED` dan pesan generik `Unauthorized device`.
Pesan yang sama mencegah API mengungkap apakah ID perangkat valid atau perangkat
telah dicabut. Header yang tidak lengkap juga ditolak sebagai 401, bukan sebagai
validasi 422.

Hanya autentikasi sukses yang memperbarui `last_seen_at` dan `last_ip`. Request
gagal tidak memperbarui heartbeat/presence. Session SQLAlchemy bersifat request-scoped:
commit setelah request sukses, rollback saat exception, dan selalu ditutup.

Device Key dibuat dari 32 byte acak, hanya ditampilkan sekali ketika perangkat baru
didaftarkan/di-seed, dan tidak dapat dipulihkan dari database karena hanya hash SHA-256
yang disimpan. Seed development dapat menampilkan kunci perangkat baru; jangan
menjalankannya pada database produksi. Rotasi/revoke key harus dilakukan melalui
alur administrasi yang akan dibangun pada fase WebUI.

Device Key adalah bearer credential. Hash token tidak menggantikan TLS. Gunakan
HTTPS/WSS bila trafik melewati jaringan yang tidak sepenuhnya dipercaya, batasi akses
LAN, rotasi/revoke Device Key saat terindikasi bocor, dan jangan menyertakan token
pada URL atau log.

P5 tidak membuat endpoint `/admin/*` atau Admin API Token. Sesuai Section 4.1 dan
Section 16 #17, P14 wajib memastikan route `/admin/*` hanya menerima session cookie
dan menolak setiap header `Authorization`.

## Pengelolaan kunci dan secret

- Buat `DATA_KEY` dengan perintah pada `server/.env.example`; hasilnya harus Base64
  dari tepat 32 byte acak. Placeholder di file contoh bukan kunci yang dapat dipakai.
- Buat `PIN_PEPPER` secara independen sebagai string acak panjang. Jangan memakai
  password Admin, `DATA_KEY`, atau nilai contoh sebagai pepper produksi.
- Simpan secret di environment/secret manager server, batasi permission file
  `.env`, jangan commit file `.env`, dan jangan tampilkan secret pada log, backup
  publik, issue, atau screenshot.
- Backup `DATA_KEY` dan `PIN_PEPPER` secara terenkripsi di lokasi terpisah dengan
  kontrol akses ketat. Kehilangan `DATA_KEY` membuat NIK terenkripsi tidak dapat
  dipulihkan; kehilangan pepper membuat hash PIN tidak dapat diverifikasi.
- Rotasi `DATA_KEY` memerlukan proses decrypt/re-encrypt NIK dan pembangunan ulang
  blind index secara atomik. Rotasi pepper memerlukan proses rehash PIN yang
  terotorisasi. Jangan sekadar mengganti environment variable.
- Kunci pengujian harus dibuat acak per proses/sesi pytest; jangan pernah memakai
  secret produksi di CI.

## Risiko PIN empat digit dan mitigasi (Section 4.3)

PIN empat digit hanya memiliki 10.000 kemungkinan. Argon2id dan pepper menaikkan biaya
serangan, tetapi **tidak menjadikan PIN empat digit kuat terhadap brute-force offline**
jika cache/verifier perangkat berhasil dicuri. Salt bukan rahasia dan tidak menambah
entropi PIN.

Mitigasi wajib sesuai spesifikasi:

1. Server mengunci kartu otomatis setelah **3** PIN salah; hanya Admin yang dapat
   membuka kunci atau proses reset PIN yang diizinkan.
2. Mode offline dibatasi oleh allowance per kartu/perangkat dan batas nominal
   transaksi offline. Nilai default allowance dan batas transaksi ditentukan di
   konfigurasi offline Section 10.
3. Cache perangkat harus dienkripsi (AES-GCM sesuai keputusan Section 17), dengan
   perlindungan kunci yang sesuai kemampuan perangkat.
4. PIN tidak pernah ditulis ke log, disimpan plaintext di server/perangkat, atau
   dikirim selain saat satu transaksi yang memerlukannya.
5. Kartu yang terkunci, PIN yang gagal, dan status perangkat harus ditangani oleh
   service transaksi; helper kriptografi tidak mengimplementasikan lockout.

UID NFC dapat dikloning dan perangkat yang offline tidak dapat segera mengetahui
status kartu terbaru. Karena itu UID bukan faktor autentikasi tunggal: transaksi
selalu memerlukan PIN, allowance offline membatasi paparan, dan sinkronisasi server
tetap menjadi sumber kebenaran saldo. Dalam mode offline lunak, transaksi yang
ditolak saat sinkronisasi karena saldo tidak cukup dicatat sebagai Shortfall/Loss;
saldo member tidak boleh menjadi negatif.
