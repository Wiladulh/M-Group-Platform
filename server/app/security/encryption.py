"""Fernet encryption and keyed blind indexing for NIK values."""

import base64
import binascii
import hashlib
import hmac

from cryptography.fernet import Fernet

from app.config import Settings


def _load_fernet_key() -> bytes:
    """Load DATA_KEY and require Base64 encoding of exactly 32 raw bytes."""
    encoded = Settings().data_key.get_secret_value()
    normalized = encoded.translate(str.maketrans("-_", "+/"))
    try:
        raw = base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("DATA_KEY harus berupa Base64 yang valid") from exc
    if len(raw) != 32:
        raise ValueError("DATA_KEY harus mendekode tepat 32 byte")
    return base64.urlsafe_b64encode(raw)


def encrypt_nik(plain: str) -> str:
    """Encrypt a NIK string using Fernet and the configured DATA_KEY."""
    return Fernet(_load_fernet_key()).encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_nik(token: str) -> str:
    """Decrypt a Fernet NIK token; invalid tokens/keys raise InvalidToken."""
    return Fernet(_load_fernet_key()).decrypt(token.encode("ascii")).decode("utf-8")


def blind_index_nik(plain: str) -> str:
    """Return a deterministic HMAC-SHA256 index keyed by the raw DATA_KEY."""
    return hmac.new(
        base64.urlsafe_b64decode(_load_fernet_key()),
        plain.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def mask_nik(nik: str) -> str:
    """Expose only the first and last four characters when long enough."""
    if len(nik) <= 8:
        return "•" * len(nik)
    return f"{nik[:4]}{'•' * (len(nik) - 8)}{nik[-4:]}"
