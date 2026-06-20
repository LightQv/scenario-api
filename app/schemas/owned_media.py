from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    source: str
    last_synced_at: datetime
    metadata_synced_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


class OwnedMediaStatusResponse(BaseModel):
    tmdb_id: int
    media_type: str
    owned: bool


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
