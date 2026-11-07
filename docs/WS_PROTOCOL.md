# Device WebSocket Protocol

Endpoint: `/ws/device` (WebSocket; not a REST endpoint). Device credentials are sent only in the first `hello` envelope body, never in the URL.

## Envelope

Every message in both directions uses `{ "v": 1, "id": "<uuid>", "type": "...", "ts": 1793966400, "data": {} }`. `ts` is Unix epoch seconds; persisted and ISO timestamps are UTC. Message IDs correlate replies and acknowledgements.

## Handshake

```mermaid
sequenceDiagram
  participant D as Device
  participant S as Server
  D->>S: hello (device_id, token, fw_version, mode?)
  S->>S: verify active device and token hash
  S->>D: hello_ok (same id, server_time_utc, timing)
  loop Connected
    D->>S: ping
    S->>D: pong (same id)
    D->>S: status / ack
  end
```

## Message types

| Direction | Type | Data |
|---|---|---|
| Device → Server | hello | device_id, token, fw_version, optional cashier mode |
| Server → Device | hello_ok | device_id, server_time_utc, ping_interval_s=10, pong_timeout_s=25, idle_disconnect_s=30 |
| Both | ping / pong | pong includes server_time_utc |
| Both | ack | id of acknowledged server envelope |
| Device → Server | status | state: idle or busy |
| Server → Device | bind.start | P11 payload; reserved in P10 |
| Device → Server | bind.card_scanned, bind.pin_submitted, bind.cancel | P11 payload; reserved in P10 |
| Server → Device | bind.error, bind.done, bind.cancel | P11 payload; reserved in P10 |
| Server → Device | catalog.changed | version |
| Server → Device | cache.invalidate | uid_list or all |
| Server → Device | cache.update | uid, balance_snapshot, offline_allowance, card_status |
| Server → Device | card.status_changed | uid, status |
| Server → Device | config.changed | keys |
| Server → Device | force_disconnect | reason |

Heartbeat: devices should ping every 10 seconds; pong timeout is 25 seconds. No inbound message for 30 seconds closes the socket.

## Close codes

| Code | Meaning |
|---:|---|
| 4001 | Replaced by a newer connection |
| 4002 | Hello required or invalid handshake |
| 4003 | Unauthorized or revoked device |
| 4004 | bind.* received before P11 support |
| 4005 | Idle timeout |
| 4006 | Heartbeat timeout |

P10 implements handshake, ping/pong, status, and committed cache/card event broadcast. Binding handlers are intentionally deferred to P11.
