"""Central domain errors and stable Indonesian API messages."""

from typing import Any


ERROR_MESSAGES = {
    "INSUFFICIENT_BALANCE": "Saldo tidak cukup",
    "INVALID_PIN": "PIN salah. Sisa percobaan: {attempts_left}",
    "CARD_LOCKED": "Kartu terkunci. Hubungi admin",
    "CARD_INACTIVE": "Kartu tidak aktif",
    "CARD_UNKNOWN": "Kartu tidak terdaftar",
    "MEMBER_SUSPENDED": "Member nonaktif",
    "CLOCK_SKEW": "Jam perangkat tidak sinkron. Hubungi admin.",
    "DUPLICATE_TXN": "Transaksi duplikat",
    "VALIDATION_ERROR": "{detail}",
}


class DomainError(Exception):
    """Base error carrying a stable API code, HTTP status, and safe details."""

    code = "VALIDATION_ERROR"
    status_code = 400

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        message_format: str | None = None,
    ) -> None:
        self.code = code or type(self).code
        self.status_code = status_code if status_code is not None else type(self).status_code
        self.details = details or {}
        self.message_format = message_format or ERROR_MESSAGES.get(self.code, "{detail}")
        self.rendered_message = message or self._render()
        self.message = self.rendered_message
        super().__init__(self.rendered_message)

    def _render(self) -> str:
        values = dict(self.details)
        values.setdefault("detail", "Permintaan tidak valid")
        try:
            return self.message_format.format(**values)
        except (KeyError, ValueError):
            return self.message_format


class ClockSkewError(DomainError):
    """Backward-compatible CLOCK_SKEW error used by earlier phases."""

    code = "CLOCK_SKEW"
    status_code = 409
