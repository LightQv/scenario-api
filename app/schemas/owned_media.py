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
