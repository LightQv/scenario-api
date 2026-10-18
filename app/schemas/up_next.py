"""Typed private release-feed contract."""

from datetime import date as CalendarDate
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    excluded: list[ExcludedShow] = Field(default_factory=list)
    unavailable: int = 0


class EpisodeWatched(BaseModel):
    """Idempotent regular-episode write; no client-supplied owner or air date."""

    model_config = ConfigDict(extra="forbid")
    season_number: int = Field(strict=True, gt=0, le=10000)
    episode_number: int = Field(strict=True, gt=0, le=10000)


class CaughtUpRequest(BaseModel):
    """Freeze bulk progress to the exact date shown in the feed, including on retry."""

    model_config = ConfigDict(extra="forbid")
    through: CalendarDate
