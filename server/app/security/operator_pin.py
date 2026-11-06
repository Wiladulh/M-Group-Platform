"""Operator six-digit PIN hashing and validation."""
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

_HASHER = PasswordHasher(type=Type.ID)


def validate_operator_pin(pin: str) -> None:
    """Require six digits and reject trivial values."""
    if not isinstance(pin, str) or len(pin) != 6 or not pin.isascii() or not pin.isdigit():
        raise ValueError("PIN operator harus terdiri dari tepat 6 digit angka")
    if pin == "000000" or pin == "123456" or len(set(pin)) == 1:
        raise ValueError("PIN operator terlalu mudah ditebak")


def hash_operator_pin(pin: str) -> str:
    validate_operator_pin(pin)
    return _HASHER.hash(pin)


def verify_operator_pin(pin: str, hashed: str) -> bool:
    try:
        return _HASHER.verify(hashed, pin)
    except (InvalidHashError, VerificationError, TypeError):
        return False
