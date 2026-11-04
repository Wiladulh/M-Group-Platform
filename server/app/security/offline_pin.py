"""Deterministic offline PIN verifier for constrained device caches."""

import hashlib
import hmac
import secrets

_ITERATIONS = 20_000
_DKLEN = 32
_SALT_LENGTH = 16


def compute_offline_verifier(pin: str, salt: bytes) -> bytes:
    """Derive a 32-byte PBKDF2-HMAC-SHA256 verifier."""
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, _ITERATIONS, dklen=_DKLEN)


def verify_offline_pin(pin: str, salt: bytes, verifier: bytes) -> bool:
    """Constant-time comparison of the derived offline verifier."""
    return hmac.compare_digest(compute_offline_verifier(pin, salt), verifier)


def generate_salt() -> bytes:
    """Generate a cryptographically random 16-byte salt."""
    return secrets.token_bytes(_SALT_LENGTH)
