"""Download request schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RadarrMovieDownloadCreate(BaseModel):
    """Request body for creating a Radarr movie download request."""

    tmdb_id: int = Field(gt=0, description="TMDB movie identifier")


class DownloadRequestResponse(BaseModel):
    """Download request response returned to the mobile app."""

    id: UUID
    user_id: UUID | None = None
    tmdb_id: int
    media_type: str
    source: str
    status: str
    radarr_movie_id: int | None = None
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
