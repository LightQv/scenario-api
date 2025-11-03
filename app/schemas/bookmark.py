"""
Bookmark schemas for request/response validation.

This module defines Pydantic schemas for bookmark operations.
Bookmarks are media items marked as PENDING in the system watchlist.
"""

from pydantic import BaseModel
from typing import List


class BookmarkCreate(BaseModel):
    """
    Schema for creating a new bookmark.

    Bookmarks are automatically added to the user's system watchlist
    with type PENDING.
    """
    tmdb_id: int
    genre_ids: List[int] = [0]
    poster_path: str
    backdrop_path: str
    release_date: str
    runtime: int
    title: str
    media_type: str
