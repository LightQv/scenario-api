"""Badge API response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer


ROMAN_SUFFIXES = {"i": "I", "ii": "II", "iii": "III", "iv": "IV"}


def badge_id_to_camel(value: str) -> str:
    """Convert backend snake_case badge IDs to frontend camelCase IDs.

    Args:
        value: Backend badge identifier.

    Returns:
        str: CamelCase identifier with uppercase Roman tier suffixes.
    """
    parts = value.split("_")
    suffix = parts[-1]
    body = parts[:-1] if suffix in ROMAN_SUFFIXES else parts
    camel = body[0] + "".join(part.capitalize() for part in body[1:])
    return f"{camel}{ROMAN_SUFFIXES[suffix]}" if suffix in ROMAN_SUFFIXES else camel


class BadgeResponse(BaseModel):
    """One badge with current progress and unlock state."""

    id: str = Field(description="Stable badge identifier")
    title: str = Field(description="Default badge title")
    description: str = Field(description="Default badge description")
    current: int = Field(ge=0, description="Current progress value")
    target: int = Field(gt=0, description="Progress needed to unlock")
    icon: str = Field(description="Ionicons icon name used by the client")
    tier: str = Field(description="Visual tier used by the client")
    unlocked: bool = Field(description="Whether the badge is permanently unlocked")
    unlocked_at: datetime | None = Field(default=None, description="When the badge was first unlocked")

    @field_serializer("id")
    def serialize_id(self, value: str) -> str:
        """Serialize backend badge IDs for the Expo client."""
        return badge_id_to_camel(value)


class BadgeListResponse(BaseModel):
    """All profile badges for the authenticated user."""

    badges: list[BadgeResponse]
