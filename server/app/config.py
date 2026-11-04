"""Application settings loaded from environment variables or a local .env file."""

import base64
import binascii
from functools import lru_cache
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the M-Group server."""

    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("local-dev-change-this-password")
    data_key: SecretStr = SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    pin_pepper: SecretStr = SecretStr("local-development-pin-pepper-change-me")
    app_version: str = "1.3.0"
    enable_api_docs: bool = True
    alert_webhook_url: str = ""
    database_url: str = "sqlite:///./mgroup.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("data_key")
    @classmethod
    def validate_data_key(cls, value: SecretStr) -> SecretStr:
        """Require DATA_KEY to be valid base64 encoding of exactly 32 bytes."""
        encoded = value.get_secret_value()
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("DATA_KEY must be valid base64") from exc
        if len(decoded) != 32:
            raise ValueError("DATA_KEY must decode to exactly 32 bytes")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
