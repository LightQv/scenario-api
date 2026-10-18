"""Private current-history snapshot; dates describe recording, not playback."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from app.schemas.view import ViewResponse


class InsightView(ViewResponse):
    """Allowlisted legacy media fields with an optional trustworthy recording date."""

    recorded_at: datetime | None = Field(
        default=None,
        description=(
            "UTC recording instant, not a playback date. "
            "Legacy/imported dates may be unknown."
        ),
    )

    @field_validator("recorded_at")
    @classmethod
    def reliable_date(cls, value: datetime | None) -> datetime | None:
        """Omit ambiguous naive timestamps instead of inventing an offset."""
        if value is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)


class ViewInsights(BaseModel):
    """Atomic owner-scoped snapshot, never merged with a legacy history read."""

    date_semantics: Literal["recorded_at"] = "recorded_at"
    views: list[InsightView]
