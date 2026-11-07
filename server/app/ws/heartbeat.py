"""Per-device heartbeat timestamps and liveness decisions."""

from datetime import UTC, datetime


class HeartbeatTracker:
    def __init__(self) -> None:
        self._last_ping_utc: dict[int, datetime] = {}
        self._last_pong_utc: dict[int, datetime] = {}

    def record_ping(self, device_id_pk: int) -> None:
        self._last_ping_utc[device_id_pk] = datetime.now(UTC)

    def record_pong(self, device_id_pk: int) -> None:
        self._last_pong_utc[device_id_pk] = datetime.now(UTC)

    def is_alive(self, device_id_pk: int) -> bool:
        now = datetime.now(UTC)
        ping = self._last_ping_utc.get(device_id_pk)
        pong = self._last_pong_utc.get(device_id_pk)
        if ping is None:
            return True
        if (now - ping).total_seconds() > 30:
            return False
        return pong is None or pong >= ping or (now - pong).total_seconds() <= 25

    def clear(self, device_id_pk: int) -> None:
        self._last_ping_utc.pop(device_id_pk, None)
        self._last_pong_utc.pop(device_id_pk, None)


heartbeat = HeartbeatTracker()
