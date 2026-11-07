# Dokumentasi API

Kontrak cashier P6 berada di bawah prefix `/api/v1`. Nominal adalah integer Rupiah.
Ketiga endpoint memerlukan `Authorization: Bearer <device_token>` dan
`X-Device-Id: CSH-001`. Timestamp request berupa Unix epoch seconds dengan toleransi
±300 detik; timestamp response berupa ISO 8601 UTC.

## POST /api/v1/payments

Memproses debit ledger online secara atomik. PIN salah menambah counter kartu; percobaan
ketiga mengunci kartu. Debit, row transaksi, reset counter, dan refresh offline allowance
berada dalam transaksi yang sama.

Request:

```json
{
  "txn_uuid": "cashier-transaction-0001",
  "uid": "A1B2C3D4",
  "amount": 5000,
  "ts": 1793966400,
  "pin": "4610"
}
```

`txn_uuid` 1–64 karakter; UID uppercase hex 8/14/20 karakter (4/7/10 byte);
amount integer positif; PIN tepat empat digit.

Response 200:

```json
{
  "txn_uuid": "cashier-transaction-0001",
  "member_code": "MG-A00001",
  "full_name": "Member Example",
  "amount": 5000,
  "balance_before": 20000,
  "balance_after": 15000,
  "status": "COMPLETED",
  "occurred_at_utc": "2026-11-06T03:00:00Z"
}
```

UUID dan payload bisnis identik mengembalikan row asli (200) tanpa debit kedua. UUID
sama dengan payload berbeda menghasilkan 409.

## POST /api/v1/balance-check

Memverifikasi kartu/PIN dan mengembalikan saldo tanpa membuat ledger row. Keberhasilan
membuat satu audit log `balance_check`. PIN failure menggunakan counter lockout yang
sama dengan payment.

Request:

```json
{"uid":"A1B2C3D4","pin":"4610","ts":1793966400}
```

Response 200:

```json
{
  "member_code": "MG-A00001",
  "full_name": "Member Example",
  "balance": 20000,
  "as_of_utc": "2026-11-06T03:00:00Z"
}
```

## GET /api/v1/transactions/{txn_uuid}

Mengambil status transaksi milik device pemanggil.

```http
GET /api/v1/transactions/cashier-transaction-0001
```

Response 200:

```json
{
  "txn_uuid": "cashier-transaction-0001",
  "type": "PAYMENT",
  "direction": "DEBIT",
  "amount": 5000,
  "status": "COMPLETED",
  "balance_before": 20000,
  "balance_after": 15000,
  "occurred_at_utc": "2026-11-06T03:00:00Z",
  "reject_reason": null
}
```

Transaksi hilang dan transaksi milik device lain sama-sama menghasilkan 404 dan pesan
`Transaksi tidak ditemukan`, sehingga keberadaan transaksi tidak bocor.

## Error envelope dan status

Semua error memakai bentuk
`{"error":{"code":"INVALID_PIN","message":"PIN salah. Sisa percobaan: 2","details":{"attempts_left":2}}}`.

| HTTP | Code | Pesan Indonesia |
|---:|---|---|
| 200 | sukses / duplicate identik | — |
| 400 | CLOCK_SKEW | Jam perangkat tidak sinkron. Hubungi admin. |
| 400 | VALIDATION_ERROR | Permintaan tidak valid / detail validasi |
| 401 | DEVICE_REVOKED | Unauthorized device |
| 404 | VALIDATION_ERROR | Transaksi tidak ditemukan |
| 409 | DUPLICATE_TXN | Transaksi duplikat |
| 422 | INSUFFICIENT_BALANCE | Saldo tidak cukup |
| 422 | INVALID_PIN | PIN salah. Sisa percobaan: {attempts_left} |
| 422 | CARD_LOCKED | Kartu terkunci. Hubungi admin |
| 422 | CARD_INACTIVE | Kartu tidak aktif |
| 422 | CARD_UNKNOWN | Kartu tidak terdaftar |
| 422 | MEMBER_SUSPENDED | Member nonaktif |

Autentikasi memakai pesan generik `DEVICE_REVOKED`. Endpoint P5
`GET /api/v1/device/config` tetap tersedia.


## POST /api/v1/topups

Cashier-only member top-up. Memerlukan device bearer auth dan header `X-Device-Id`.
Request berisi `txn_uuid`, UID kartu uppercase HEX, nominal integer Rupiah, nomor dan PIN operator 6 digit, PIN member 4 digit, serta `ts` Unix seconds.
Nominal harus kelipatan Rp1.000, minimal `topup_min` (default Rp5.000), maksimal `topup_max` (default Rp1.000.000). Operator wajib aktif, tidak terkunci, dan terikat ke Cashier tersebut. UUID identik mengembalikan hasil awal; payload berbeda menghasilkan 409.


## Device WebSocket

The device transport is a WebSocket endpoint, not REST: connect to `/ws/device` and follow [WS_PROTOCOL.md](WS_PROTOCOL.md). The device token is sent in the first `hello.data.token` field, never in the URL. Existing REST endpoints are unchanged.


## Remote card binding

P11 provides the binding state machine and device WebSocket messages only. It does not add an admin REST route or WebUI. The future `POST /admin/bind-sessions` endpoint is reserved for P14.


## POST /api/v1/device/sync

Device-authenticated offline transaction synchronization. The request contains a
unique `batch_uuid` and at most 50 items. Items are processed sequentially in
ascending `offline_ts` order, regardless of their order in the submitted array.

```json
{
  "batch_uuid": "batch-2026-11-08-001",
  "items": [{
    "txn_uuid": "offline-payment-0001",
    "uid": "A1B2C3D4",
    "slot_no": null,
    "product_id": null,
    "manual_amount": null,
    "price": 5000,
    "offline_ts": 1794099600,
    "ts_untrusted": null,
    "dispense_result": null,
    "pin_fail_events": 0
  }]
}
```

Each result is `ACCEPTED`, `DUPLICATE`, or `REJECTED`. Rejected known-member
items are recorded as `transactions.status=REJECTED` without changing balance.
An insufficient-at-sync result additionally creates an OPEN
`shortfall_records` row. Unknown-card and UUID-conflict rejections are recorded
in the batch detail log only because a transaction row cannot safely be linked
to a member or would violate the unique transaction UUID constraint.

The same `batch_uuid` from the same device returns the stored result as
`DUPLICATE` without replaying writes. Repeating an item UUID with identical
business payload returns the original balance; a changed payload returns
`DUPLICATE_TXN_CONFLICT`. Item-level rejections do not fail the batch.

## GET /api/v1/device/member-cache?since={version}

Returns changed member-cache entries for the authenticated device, limited to
the top 100 members selected by the offline cache policy. A matching version
returns HTTP 200 with an empty `entries` array; a future version returns HTTP
400 `VALIDATION_ERROR`.

```json
{
  "cache_version": 12,
  "entries": [{
    "uid": "A1B2C3D4",
    "member_code": "MG-A00001",
    "name": "Member Example",
    "balance_snapshot": 15000,
    "snapshot_ts": "2026-11-08T02:00:00Z",
    "offline_allowance": 10000,
    "card_status": "ACTIVE",
    "entry_version": 12
  }]
}
```

Both endpoints require `Authorization: Bearer <device_token>` and
`X-Device-Id`. Batch size over 50 returns HTTP 400 `VALIDATION_ERROR`.
