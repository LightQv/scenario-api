"""
Bookmark service for managing pending media items.

This module provides service functions for creating, retrieving, and deleting bookmarks.
Bookmarks are media items with type PENDING stored in the user's system watchlist.
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status
from uuid import UUID
from typing import List

from app.models import Media, Watchlist, User
from app.models.enums import MediaType, WatchlistType
from app.schemas import BookmarkCreate, MediaResponse


def get_system_watchlist(user_id: UUID, database_session: Session) -> Watchlist:
    """
    Get or find the user's system watchlist.

    Args:
        user_id: UUID of the user
        database_session: Database session

    Returns:
        Watchlist: The user's system watchlist

    Raises:
        HTTPException: 404 if system watchlist not found
    """
    system_watchlist = (
        database_session.query(Watchlist)
        .filter(
            Watchlist.author_id == user_id,
            Watchlist.type == WatchlistType.SYSTEM.value
        )
        .first()
    )

    if not system_watchlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System watchlist not found"
        )

    return system_watchlist


def get_user_bookmarks(
    user_id: UUID,
    database_session: Session
) -> List[MediaResponse]:
    """
    Get all bookmarks for a specific user.

    Retrieves all PENDING media items from the user's system watchlist.

    Args:
        user_id: UUID of the user
        database_session: Database session

    Returns:
        List[MediaResponse]: List of bookmarked media items

    Raises:
        HTTPException: 404 if system watchlist not found
    """
    # Get the user's system watchlist
    system_watchlist = get_system_watchlist(user_id, database_session)

    # Query all PENDING media items in the system watchlist
    bookmarks = (
        database_session.query(Media)
        .filter(
            Media.watchlist_id == system_watchlist.id,
            Media.type == MediaType.PENDING.value
        )
        .all()
    )

    return [MediaResponse.model_validate(bookmark) for bookmark in bookmarks]


def create_bookmark(
    bookmark_data: BookmarkCreate,
    current_user: User,
    database_session: Session
) -> dict:
    """
    Create a new bookmark (pending media item).

    Adds a media item with type PENDING to the user's system watchlist.

    Args:
        bookmark_data: Bookmark creation data
        current_user: Currently authenticated user
        database_session: Database session

    Returns:
        dict: Success message

    Raises:
        HTTPException: 404 if system watchlist not found
    """
    # Get the user's system watchlist
    system_watchlist = get_system_watchlist(current_user.id, database_session)

    # Create the bookmark with PENDING type
    new_bookmark = Media(
        tmdb_id=bookmark_data.tmdb_id,
        genre_ids=bookmark_data.genre_ids,
        poster_path=bookmark_data.poster_path,
        backdrop_path=bookmark_data.backdrop_path,
        release_date=bookmark_data.release_date,
        runtime=bookmark_data.runtime,
        title=bookmark_data.title,
        media_type=bookmark_data.media_type,
        type=MediaType.PENDING.value,
        watchlist_id=system_watchlist.id,
    )

    database_session.add(new_bookmark)
    database_session.commit()

    return {"message": "Bookmark created successfully"}


def delete_bookmark(
    media_id: UUID,
    current_user: User,
    database_session: Session
) -> None:
    """
    Delete a bookmark (pending media item).

    Removes a media item from the user's system watchlist.
    Only works for PENDING media items in the system watchlist.

    Args:
        media_id: UUID of the media item to delete
        current_user: Currently authenticated user
        database_session: Database session

    Raises:
        HTTPException:
            - 404 if media doesn't exist
            - 403 if user doesn't own the media or media is not a bookmark
    """
    media = database_session.query(Media).filter(Media.id == media_id).first()

    if not media:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bookmark not found"
        )

    # Verify the media belongs to a system watchlist
    watchlist = (
        database_session.query(Watchlist)
        .filter(Watchlist.id == media.watchlist_id)
        .first()
    )

    if not watchlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist not found"
        )

    # Verify user owns the watchlist
    if str(watchlist.author_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this bookmark"
        )

    # Verify it's a system watchlist
    if watchlist.type != WatchlistType.SYSTEM.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only delete bookmarks from system watchlist"
        )

    # Verify it's a PENDING media item
    if media.type != MediaType.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only delete PENDING media items as bookmarks"
        )

    database_session.delete(media)
    database_session.commit()
