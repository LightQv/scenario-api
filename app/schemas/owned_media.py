from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RadarrWebhookPayload(BaseModel):
    eventType: str | None = None
    movie: dict | None = None
    movieFile: dict | None = None
    isUpgrade: bool | None = None
    deleteReason: str | None = None
    data: dict | None = None

    model_config = ConfigDict(extra="allow")


class SonarrWebhookPayload(BaseModel):
    eventType: str | None = None
    series: dict | None = None
    episodes: list[dict] | None = None
    episode: dict | None = None
    episodeFile: dict | None = None
    release: dict | None = None
    isUpgrade: bool | None = None
    deleteReason: str | None = None
    data: dict | None = None

    model_config = ConfigDict(extra="allow")


class RadarrWebhookResponse(BaseModel):
    status: str
    event_type: str | None = None
    action: str
    tmdb_id: int | None = None


class SonarrWebhookResponse(BaseModel):
    status: str
    event_type: str | None = None
    action: str
    tmdb_id: int | None = None
    season_number: int | None = None
    episode_number: int | None = None


class OwnedMediaResponse(BaseModel):
    id: UUID
    tmdb_id: int
    genre_ids: list[int]
    poster_path: str
    backdrop_path: str
    release_date: str
    release_year: str
    runtime: int
    title: str
    media_type: str
    scope: str
    tvdb_id: int | None = None
    sonarr_series_id: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None
    episode_air_date: str | None = None
    source: str
    last_synced_at: datetime
    metadata_synced_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


class OwnedMediaStatusResponse(BaseModel):
    tmdb_id: int
    media_type: str
    owned: bool
    status: str | None = None
    available_episode_count: int | None = None
    aired_episode_count: int | None = None


class OwnedMediaDeleteResponse(BaseModel):
    tmdb_id: int
    media_type: str
    scope: str
    season_number: int | None = None
    deleted_count: int


class OwnedMediaSyncResponse(BaseModel):
    source: str = Field(description="Integration source used for the sync")
    media_type: str = Field(description="Media type synced from the source")
    owned_count: int = Field(description="Number of owned media rows stored")
    synced_at: datetime = Field(description="Timestamp when the sync completed")


class OwnedMediaSyncStatusResponse(BaseModel):
    source: str
    media_type: str
    status: str
    trigger: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    owned_count: int | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TvEpisodeAvailabilityResponse(BaseModel):
    episode_number: int
    status: str


class TvSeasonAvailabilityResponse(BaseModel):
    season_number: int
    status: str
    available_episode_count: int
    aired_episode_count: int
    episodes: list[TvEpisodeAvailabilityResponse] = []


class TvAvailabilityResponse(BaseModel):
    tmdb_id: int
    media_type: str = "tv"
    status: str
    available_episode_count: int
    aired_episode_count: int
    seasons: list[TvSeasonAvailabilityResponse]
