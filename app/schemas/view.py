from pydantic import BaseModel, ConfigDict
from typing import List
from uuid import UUID


class ViewBase(BaseModel):
    tmdb_id: int
    genre_ids: List[int] = [0]
    poster_path: str
    backdrop_path: str
    release_date: str
    release_year: str
    runtime: int
    title: str
    media_type: str


class ViewCreate(ViewBase):
    viewer_id: UUID


class ViewResponse(BaseModel):
    id: UUID
    tmdb_id: int
    genre_ids: List[int]
    poster_path: str
    backdrop_path: str
    release_date: str
    release_year: str
    runtime: int
    title: str
    media_type: str
    viewer_id: UUID

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, str_strip_whitespace=True
    )


class ViewCountByType(BaseModel):
    media_type: str
    count: int


class ViewCountByYear(BaseModel):
    release_year: str
    count: int


class ViewRuntime(BaseModel):
    runtime: int
