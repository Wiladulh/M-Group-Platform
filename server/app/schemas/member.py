"""Member registration form schema."""

from pydantic import BaseModel, Field, field_validator


class MemberCreateForm(BaseModel):
    """Validated input for creating a member account."""

    full_name: str = Field(min_length=3, max_length=100)
    nik: str = Field(min_length=1, max_length=64)
    phone: str = Field(pattern=r"^(\+62|62|0)8\d{8,12}$")
    initial_balance: int = Field(default=0, ge=0, multiple_of=1000)
    notes: str | None = None

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        """Normalize Indonesian mobile prefixes to the local 08 format."""
        if not isinstance(value, str):
            return value
        value = value.strip()
        if value.startswith("+62"):
            return "0" + value[3:]
        if value.startswith("62"):
            return "0" + value[2:]
        return value

    @field_validator("full_name", "nik", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        """Trim surrounding whitespace from required text fields."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        """Convert blank notes to None."""
        if isinstance(value, str):
            return value.strip() or None
        return value
