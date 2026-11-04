"""Device authentication token generation and hashing."""

import hashlib
import hmac
import secrets


def generate_device_token() -> str:
    """Generate a URL-safe token containing 32 random bytes."""
    return secrets.token_urlsafe(32)


def hash_device_token(token: str) -> str:
    """Return the SHA-256 hex digest of a device token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_device_token(token: str, hashed: str) -> bool:
    """Verify a token hash using a constant-time digest comparison."""
    return hmac.compare_digest(hash_device_token(token), hashed)
