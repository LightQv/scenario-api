"""Download request schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RadarrMovieDownloadCreate(BaseModel):
    """Request body for creating a Radarr movie download request."""

    tmdb_id: int = Field(gt=0, description="TMDB movie identifier")


class SonarrSeriesDownloadCreate(BaseModel):
    """Request body for creating a Sonarr series download request."""

    tmdb_id: int = Field(gt=0, description="TMDB TV series identifier")


class SonarrSeasonDownloadCreate(BaseModel):
    """Request body for creating a Sonarr season download request."""

    tmdb_id: int = Field(gt=0, description="TMDB TV series identifier")
    season_number: int = Field(ge=1, description="Regular season number")


class DownloadRequestResponse(BaseModel):
    """Download request response returned to the mobile app."""

    id: UUID
    user_id: UUID | None = None
    tmdb_id: int
    media_type: str
    scope: str
    source: str
    status: str
    radarr_movie_id: int | None = None
    radarr_search_command_id: int | None = None
    tvdb_id: int | None = None
    sonarr_series_id: int | None = None
    sonarr_search_command_id: int | None = None
    sonarr_episode_id: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    genre_ids: list[int]
    poster_path: str
    backdrop_path: str
    release_date: str
    release_year: str
    runtime: int
    title: str
    error_message: str | None = None
    download_title: str | None = None
    download_client: str | None = None
    quality: str | None = None
    size: int | None = None
    size_left: int | None = None
    time_left: str | None = None
    tracked_download_status: str | None = None
    tracked_download_state: str | None = None
    requested_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
