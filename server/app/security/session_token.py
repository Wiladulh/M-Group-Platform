"""Admin session token generation and hashing."""

import hashlib
import hmac
import secrets


def generate_session_token() -> str:
    """Generate a URL-safe session token containing 32 random bytes."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Return the SHA-256 hex digest of a session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_session_token(token: str, hashed: str) -> bool:
    """Verify a session token hash using a constant-time comparison."""
    return hmac.compare_digest(hash_session_token(token), hashed)
