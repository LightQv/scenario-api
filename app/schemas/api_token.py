"""Schemas for user-owned long-term API tokens."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


ALLOWED_API_TOKEN_SCOPES = {
    "downloads:read",
    "downloads:create",
    "owned_media:read",
    "owned_media:sync",
}
DEFAULT_API_TOKEN_SCOPES = sorted(ALLOWED_API_TOKEN_SCOPES)


class ApiTokenCreate(BaseModel):
    """Create a long-term API token."""

    name: str = Field(..., min_length=1, max_length=100)
    token: str | None = Field(default=None, min_length=24, max_length=512)
    scopes: list[str] = Field(
        default_factory=lambda: DEFAULT_API_TOKEN_SCOPES.copy(), max_length=10
    )

    @field_validator("name", "token")
    @classmethod
    def trim_non_empty(cls, value: str | None) -> str | None:
        """Trim token form text fields and reject empty values."""
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Value cannot be empty")
        return trimmed


class ApiTokenListItem(BaseModel):
    """API token list metadata."""

    id: UUID
    name: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ApiTokenDetail(ApiTokenListItem):
    """API token detail with owner-readable token value."""

    token: str


class ApiTokenCreateResponse(ApiTokenDetail):
    """Created API token response."""


class ApiTokenGenerateResponse(BaseModel):
    """Generated token value response."""

    token: str
