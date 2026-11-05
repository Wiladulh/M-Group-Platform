"""Small domain-error contract for consistent HTTP error envelopes."""

from typing import Any


class DomainError(Exception):
    """Base error carrying a stable API code and safe public details."""

    code = "VALIDATION_ERROR"
    status_code = 400

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ClockSkewError(DomainError):
    """Raised when a device request timestamp is outside the accepted window."""

    code = "CLOCK_SKEW"
    status_code = 409
