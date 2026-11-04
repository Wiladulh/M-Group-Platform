"""CSRF token generation and constant-time verification."""

import hmac
import secrets


def generate_csrf_token() -> str:
    """Generate a cryptographically random URL-safe CSRF token."""
    return secrets.token_urlsafe(32)


def verify_csrf_token(expected: str, submitted: str) -> bool:
    """Compare CSRF tokens in constant time."""
    return hmac.compare_digest(expected, submitted)
