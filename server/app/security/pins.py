"""Online transaction PIN hashing and format validation."""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings

_PIN_HASHER = PasswordHasher(type=Type.ID)
WEAK_PINS = {
    "0000",
    "1111",
    "2222",
    "3333",
    "4444",
    "5555",
    "6666",
    "7777",
    "8888",
    "9999",
    "1234",
    "4321",
    "2580",
}


def _pin_pepper() -> str:
    """Load the configured pepper without caching environment values."""
    return Settings().pin_pepper.get_secret_value()


def hash_pin(pin: str) -> str:
    """Hash a PIN using Argon2id over PIN concatenated with the server pepper."""
    validate_pin_format(pin)
    return _PIN_HASHER.hash(pin + _pin_pepper())


def verify_pin(pin: str, hashed: str) -> bool:
    """Verify a PIN against its peppered Argon2id hash."""
    try:
        return _PIN_HASHER.verify(hashed, pin + _pin_pepper())
    except (InvalidHashError, VerificationError, TypeError):
        return False


def validate_pin_format(pin: str) -> None:
    """Require exactly four ASCII digits and reject the Section 4.3 blocklist."""
    if not isinstance(pin, str) or len(pin) != 4 or not pin.isascii() or not pin.isdigit():
        raise ValueError("PIN harus terdiri dari tepat 4 digit angka")
    if pin in WEAK_PINS:
        raise ValueError("PIN terlalu mudah ditebak. Silakan gunakan PIN lain")
