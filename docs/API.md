# Dokumentasi API

Dokumen ini merangkum kontrak endpoint REST M-Group Platform v1.3. Semua nominal uang
menggunakan integer Rupiah dan semua timestamp API menggunakan ISO 8601 UTC.

## Device

### GET /api/v1/device/config

Mengambil konfigurasi efektif perangkat setelah autentikasi. Nilai global dibaca dari
tabel `settings`, kemudian ditimpa oleh properti pada `devices.config_json`.

**Headers wajib**

```http
Authorization: Bearer <device_token>
X-Device-Id: CSH-001
```

Device Key dibuat saat registrasi/seed, ditampilkan satu kali, dan database hanya
menyimpan SHA-256 hash. Permintaan dengan token hilang, format Authorization salah,
Device ID tidak dikenal, token salah, atau perangkat REVOKED ditolak dengan HTTP 401.
Kegagalan autentikasi menggunakan pesan generik agar status perangkat tidak bocor.

**Contoh request**

```bash
curl -i http://127.0.0.1:8000/api/v1/device/config \
  -H "Authorization: Bearer <DEVICE_KEY>" \
  -H "X-Device-Id: CSH-001"
```

**Contoh response (Cashier)**

```json
{
  "device_id": "CSH-001",
  "name": "Cashier 001",
  "type": "cashier",
  "mode": "manual",
  "slot_count": null,
  "offline_enabled": true,
  "offline_txn_max": 30000,
  "offline_card_cap": 50000,
  "offline_hold_mode": "soft",
  "catalog_version": null,
  "server_time_utc": "2026-11-05T12:00:00Z",
  "device_config_overrides": {
    "offline_enabled": true
  }
}
```

Untuk Vending, `mode` bernilai null, `slot_count` berisi jumlah slot, dan
`catalog_version` berisi versi katalog (0 bila metadata belum diinisialisasi).
Field Cashier-only dan Vending-only tetap hadir sebagai null pada tipe yang tidak
menggunakannya.

**Error**

Semua error memakai envelope:

```json
{"error":{"code":"DEVICE_REVOKED","message":"Unauthorized device","details":{}}}
```

| HTTP | Code | Makna |
|---|---|---|
| 401 | DEVICE_REVOKED | Device Key hilang/salah, ID tidak cocok, atau perangkat dicabut |
| 422 | VALIDATION_ERROR | Request tidak lolos validasi |
| 409 | CLOCK_SKEW | Timestamp perangkat di luar toleransi (handler disiapkan; validasi timestamp dilakukan fase transaksi) |

Autentikasi ini khusus endpoint perangkat. Tidak ada route `/admin/*` pada P5.
