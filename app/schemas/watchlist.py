from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from uuid import UUID

from app.schemas.media import MediaResponse


class WatchlistBase(BaseModel):
    title: str = Field(..., max_length=255)


class WatchlistCreate(WatchlistBase):
    pass


class WatchlistUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)


class MediaInWatchlist(BaseModel):
    id: UUID
    tmdb_id: int

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, str_strip_whitespace=True
    )


class WatchlistResponse(BaseModel):
    id: UUID
    title: str
    type: str
    author_id: UUID
    medias: List[MediaInWatchlist] = []
    medias_count: int = 0

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, str_strip_whitespace=True
    )


class WatchlistDetail(BaseModel):
    title: str
    type: str
    medias: List["MediaResponse"] = []
    medias_count: int = 0

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, str_strip_whitespace=True
    )
