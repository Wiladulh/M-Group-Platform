"""Argon2id password hashing and admin password policy."""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

_PASSWORD_HASHER = PasswordHasher(type=Type.ID)


def hash_password(plain: str) -> str:
    """Return an Argon2id hash for a plaintext password."""
    if not isinstance(plain, str):
        raise TypeError("Password harus berupa teks")
    return _PASSWORD_HASHER.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password without leaking malformed-hash errors."""
    try:
        return _PASSWORD_HASHER.verify(hashed, plain)
    except (InvalidHashError, VerificationError, TypeError):
        return False


def validate_admin_password(
    pw: str,
    username: str,
    previous_hash_or_None: str | None,
) -> None:
    """Enforce Section 4.1 admin password rules."""
    if len(pw) < 10:
        raise ValueError("Password minimal 10 karakter")
    if not any(char.isalpha() for char in pw) or not any(char.isdigit() for char in pw):
        raise ValueError("Password harus mengandung huruf dan angka")
    if pw.casefold() == username.casefold():
        raise ValueError("Password tidak boleh sama dengan username")
    if previous_hash_or_None and verify_password(pw, previous_hash_or_None):
        raise ValueError("Password baru tidak boleh sama dengan password sebelumnya")
