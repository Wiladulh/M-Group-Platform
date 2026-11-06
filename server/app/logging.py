"""Minimal structured JSON logging with credential and identifier redaction."""

import json
import logging
import re
from datetime import UTC, datetime


class SecretRedactionFilter(logging.Filter):
    """Redact PINs, bearer credentials, device header values, full UIDs, and NIKs."""

    _patterns = (
        (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(pin[\"']?\s*[:=]\s*[\"']?)\d{4}"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)[^,}\s]+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(x-device-id[\"']?\s*[:=]\s*[\"']?)[^,}\s]+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(nik[\"']?\s*[:=]\s*[\"']?)[0-9]{8,}"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(uid[\"']?\s*[:=]\s*[\"']?)([0-9a-f]{8,20})"), None),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern, replacement in self._patterns:
            if replacement is None:
                message = pattern.sub(
                    lambda match: (
                        f"{match.group(1)}"
                        f"{'*' * (len(match.group(2)) - 4)}{match.group(2)[-4:]}"
                    ),
                    message,
                )
            else:
                message = pattern.sub(replacement, message)
        record.msg = message
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Emit compact JSON records with UTC timestamp, level, logger, and message."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger once without external dependencies."""
    root = logging.getLogger()
    if any(isinstance(item, SecretRedactionFilter) for item in root.filters):
        return
    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter())
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
