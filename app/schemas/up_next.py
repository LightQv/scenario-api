"""Typed private release-feed contract."""

from datetime import date as CalendarDate, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EpisodeRef(BaseModel):
    """Public episode identity and spoiler-safe metadata."""

    season_number: int = Field(gt=0)
    episode_number: int = Field(gt=0)
    name: str
    air_date: CalendarDate


class NextEntry(BaseModel):
    """One show or bookmarked premiere in the release feed."""

    tmdb_id: int
    media_type: Literal["movie", "tv"]
    title: str
    poster_path: str
    backdrop_path: str
    date: CalendarDate | None = None
    episode: EpisodeRef | None = None
    tracked: bool = False
    remaining: int = 0
    watched_episodes: int = 0
    aired_episodes: int = 0
    status: str = ""


class ExcludedShow(BaseModel):
    """Restorable display snapshot, not authoritative TMDB metadata."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")
    tmdb_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=300)
    poster_path: str = Field(max_length=500, pattern=r"^(?:/[^\s]*|)$")


class ShowExclusionRequest(BaseModel):
    """Owner-private display copy retained even when TMDB is unavailable."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    poster_path: str = Field(max_length=500, pattern=r"^(?:/[^\s]*|)$")


class NextFeed(BaseModel):
    """Owner-labelled feed; metadata failures remain distinguishable from emptiness."""

    user_id: UUID
    as_of: CalendarDate
    to_watch: list[NextEntry]
    upcoming: list[NextEntry]
    caught_up: list[NextEntry]
    finished: list[NextEntry] = Field(default_factory=list)
    excluded: list[ExcludedShow] = Field(default_factory=list)
    unavailable: int = 0
    syncing: bool = False
    sync_failed: bool = False
    updated_at: datetime | None = None


class EpisodeWatched(BaseModel):
    """Idempotent regular-episode write; no client-supplied owner or air date."""

    model_config = ConfigDict(extra="forbid")
    season_number: int = Field(strict=True, gt=0, le=10000)
    episode_number: int = Field(strict=True, gt=0, le=10000)
    watched: bool = Field(default=True, strict=True)


class CaughtUpRequest(BaseModel):
    """Freeze bulk progress to the exact date shown in the feed, including on retry."""

    model_config = ConfigDict(extra="forbid")
    through: CalendarDate
    watched: bool = Field(default=True, strict=True)


class WatchedEpisodeState(BaseModel):
    """Released regular episode and its authoritative private watched state."""

    season_number: int
    episode_number: int
    watched: bool
    air_date: CalendarDate | None = None


class ShowProgressState(BaseModel):
    """Owner-labelled progress for details, including shows not yet tracked."""

    user_id: UUID
    tmdb_id: int
    as_of: CalendarDate
    tracked: bool
    episodes: list[WatchedEpisodeState]
    ready: bool = True
    syncing: bool = False
    updated_at: datetime | None = None
    actions: list["ProgressActionState"] = Field(default_factory=list)


class ProgressActionRequest(BaseModel):
    """Idempotent desired state, frozen to the tap's date, never a client air date."""

    model_config = ConfigDict(extra="forbid")
    id: UUID
    season_number: int | None = Field(default=None, strict=True, gt=0, le=10000)
    episode_number: int | None = Field(default=None, strict=True, gt=0, le=10000)
    through: CalendarDate
    watched: bool = Field(strict=True)
    record_history: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def check_target(self) -> "ProgressActionRequest":
        """An episode always belongs to a positive regular season."""
        if self.episode_number is not None and self.season_number is None:
            raise ValueError("Episode requires a season")
        return self


class ProgressActionState(ProgressActionRequest):
    """Read-only receipt for accepted, applied or rejected work."""

    model_config = ConfigDict(from_attributes=True)
    status: Literal["pending", "applied", "failed", "cancelled"]


ShowProgressState.model_rebuild()
