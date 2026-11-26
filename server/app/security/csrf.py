"""HMAC-authenticated CSRF tokens for login and admin forms."""

import base64
import hashlib
import hmac
import secrets


def generate_csrf_token(key: bytes, context: str) -> str:
    """Return a random nonce authenticated with a context-specific HMAC."""
    nonce = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    signature = hmac.new(key, context.encode() + nonce.encode(), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{nonce}.{encoded}"


def verify_csrf_token(token: str, key: bytes, context: str) -> bool:
    """Verify a CSRF token without leaking signature comparison timing."""
    try:
        nonce, supplied = token.split(".", 1)
        raw = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
        expected = hmac.new(key, context.encode() + nonce.encode(), hashlib.sha256).digest()
        return bool(nonce) and hmac.compare_digest(expected, raw)
    except (ValueError, TypeError):
        return False
