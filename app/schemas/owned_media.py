from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OwnedMediaResponse(BaseModel):
    tmdb_id: int
    media_type: str
    source: str
    last_synced_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
