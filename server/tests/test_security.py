"""Exhaustive tests for the pure security primitives."""

import base64
import os

import pytest
from app.security.csrf import generate_csrf_token, verify_csrf_token
from app.security.device_token import (
    generate_device_token,
    hash_device_token,
    verify_device_token,
)
from app.security.encryption import (
    _load_fernet_key,
    blind_index_nik,
    decrypt_nik,
    encrypt_nik,
    mask_nik,
)
from app.security.offline_pin import (
    compute_offline_verifier,
    generate_salt,
    verify_offline_pin,
)
from app.security.passwords import (
    hash_password,
    validate_admin_password,
    verify_password,
)
from app.security.pins import (
    WEAK_PINS,
    hash_pin,
    validate_pin_format,
    verify_pin,
)
from app.security.session_token import (
    generate_session_token,
    hash_session_token,
    verify_session_token,
)
from cryptography.fernet import InvalidToken


def _set_data_key(monkeypatch: pytest.MonkeyPatch, raw: bytes) -> str:
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    monkeypatch.setenv("DATA_KEY", encoded)
    return encoded


def test_password_hash_verify_roundtrip() -> None:
    hashed = hash_password("CorrectHorse123")
    assert hashed.startswith("$argon2id$")
    assert verify_password("CorrectHorse123", hashed)


def test_password_wrong_value_fails() -> None:
    assert not verify_password("wrong", hash_password("CorrectHorse123"))


def test_password_malformed_hash_fails_safely() -> None:
    assert not verify_password("password", "not-an-argon2-hash")


def test_password_policy_too_short() -> None:
    with pytest.raises(ValueError, match="minimal 10"):
        validate_admin_password("Short123", "admin", None)


def test_password_policy_requires_digit() -> None:
    with pytest.raises(ValueError, match="huruf dan angka"):
        validate_admin_password("LongPassword", "admin", None)


def test_password_policy_rejects_username() -> None:
    with pytest.raises(ValueError, match="username"):
        validate_admin_password("AdminUser123", "AdminUser123", None)


def test_password_policy_rejects_previous_password() -> None:
    old_hash = hash_password("Previous123")
    with pytest.raises(ValueError, match="sebelumnya"):
        validate_admin_password("Previous123", "admin", old_hash)


def test_password_policy_accepts_valid_password() -> None:
    assert validate_admin_password("NewPassword123", "admin", None) is None


def test_pin_hash_verify_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIN_PEPPER", "test-pepper-with-enough-randomness")
    hashed = hash_pin("7391")
    assert hashed.startswith("$argon2id$")
    assert verify_pin("7391", hashed)


def test_pin_wrong_value_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIN_PEPPER", "test-pepper-with-enough-randomness")
    assert not verify_pin("7392", hash_pin("7391"))


def test_pin_malformed_hash_fails_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIN_PEPPER", "test-pepper-with-enough-randomness")
    assert not verify_pin("7391", "not-an-argon2-hash")


@pytest.mark.parametrize("pin", sorted(WEAK_PINS))
def test_pin_format_rejects_weak_blocklist(pin: str) -> None:
    with pytest.raises(ValueError, match="mudah ditebak"):
        validate_pin_format(pin)


@pytest.mark.parametrize("pin", ["123", "12345", "12a4", "１２３４", "", " 123"])
def test_pin_format_rejects_non_four_ascii_digits(pin: str) -> None:
    with pytest.raises(ValueError, match="tepat 4 digit"):
        validate_pin_format(pin)


def test_pin_format_accepts_strong_pin() -> None:
    assert validate_pin_format("7391") is None


def test_offline_verifier_roundtrip() -> None:
    salt = generate_salt()
    verifier = compute_offline_verifier("7391", salt)
    assert len(verifier) == 32
    assert verify_offline_pin("7391", salt, verifier)


def test_offline_verifier_rejects_wrong_pin() -> None:
    salt = generate_salt()
    verifier = compute_offline_verifier("7391", salt)
    assert not verify_offline_pin("7392", salt, verifier)


def test_offline_verifier_is_deterministic_for_same_salt() -> None:
    salt = b"0123456789abcdef"
    assert compute_offline_verifier("7391", salt) == compute_offline_verifier("7391", salt)


def test_offline_verifier_changes_with_salt() -> None:
    assert compute_offline_verifier("7391", b"0123456789abcdef") != compute_offline_verifier(
        "7391", b"fedcba9876543210"
    )


def test_generate_salt_returns_random_sixteen_bytes() -> None:
    first = generate_salt()
    second = generate_salt()
    assert len(first) == 16
    assert first != second


def test_nik_encryption_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_data_key(monkeypatch, b"A" * 32)
    assert decrypt_nik(encrypt_nik("3201012345678901")) == "3201012345678901"


def test_nik_decryption_with_wrong_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_data_key(monkeypatch, b"A" * 32)
    token = encrypt_nik("3201012345678901")
    _set_data_key(monkeypatch, b"B" * 32)
    with pytest.raises(InvalidToken):
        decrypt_nik(token)


def test_nik_blind_index_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_data_key(monkeypatch, b"A" * 32)
    assert blind_index_nik("3201012345678901") == blind_index_nik("3201012345678901")


def test_nik_blind_index_differs_for_different_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_data_key(monkeypatch, b"A" * 32)
    assert blind_index_nik("3201012345678901") != blind_index_nik("3201012345678902")


def test_nik_blind_index_is_not_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_data_key(monkeypatch, b"A" * 32)
    nik = "3201012345678901"
    assert blind_index_nik(nik) != nik


def test_mask_nik_hides_short_values() -> None:
    assert mask_nik("12345678") == "••••••••"
    assert mask_nik("1234") == "••••"
    assert mask_nik("") == ""


def test_mask_nik_preserves_only_first_and_last_four() -> None:
    assert mask_nik("3201012345678901") == "3201••••••••8901"


def test_device_token_generate_hash_verify() -> None:
    token = generate_device_token()
    hashed = hash_device_token(token)
    assert verify_device_token(token, hashed)
    assert not verify_device_token("different-token", hashed)


def test_session_token_generate_hash_verify() -> None:
    token = generate_session_token()
    hashed = hash_session_token(token)
    assert verify_session_token(token, hashed)
    assert not verify_session_token("different-token", hashed)


def test_csrf_token_generate_and_verify() -> None:
    token = generate_csrf_token()
    assert token
    assert verify_csrf_token(token, token)
    assert not verify_csrf_token(token, token + "x")


def test_encryption_rejects_all_zero_data_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_data_key(monkeypatch, bytes(32))
    with pytest.raises(ValueError, match="tidak boleh seluruhnya nol"):
        _load_fernet_key()


def test_config_rejects_all_zero_data_key() -> None:
    from app.config import Settings
    from pydantic import ValidationError

    encoded = base64.urlsafe_b64encode(bytes(32)).decode("ascii")
    with pytest.raises(ValidationError, match="tidak boleh seluruhnya nol"):
        Settings(data_key=encoded)


def test_encryption_still_accepts_random_32_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    import secrets

    _set_data_key(monkeypatch, secrets.token_bytes(32))
    assert len(_load_fernet_key()) == 44


def test_conftest_per_session_key_is_not_zero() -> None:
    raw = base64.urlsafe_b64decode(os.environ["DATA_KEY"])
    assert len(raw) == 32
    assert any(raw)


def test_load_fernet_key_rejects_non_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_KEY", "not base64!")
    with pytest.raises(ValueError, match="base64"):
        _load_fernet_key()


def test_load_fernet_key_rejects_wrong_decoded_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_KEY", base64.urlsafe_b64encode(b"short").decode("ascii"))
    with pytest.raises(ValueError, match="32 byte"):
        _load_fernet_key()


def test_load_fernet_key_rejects_missing_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("DATA_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        _load_fernet_key()
