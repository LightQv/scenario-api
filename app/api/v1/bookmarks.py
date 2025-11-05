"""
Bookmark API endpoints.

This module provides REST API endpoints for managing bookmarks.
Bookmarks are media items marked as PENDING in the user's system watchlist.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List

from app.api.dependencies import get_database, get_current_user
from app.models import User
from app.schemas import BookmarkCreate, MediaResponse
from app.services.bookmark_service import create_bookmark, delete_bookmark, get_user_bookmarks


router = APIRouter(
    tags=["Bookmarks"],
    responses={
        404: {"description": "Bookmark not found"},
        403: {"description": "Access forbidden"},
    },
)


@router.get(
    "/{user_id}",
    response_model=List[MediaResponse],
    summary="Get user bookmarks",
    description="Retrieve all bookmarked media items for a specific user",
)
def get_bookmarks(
    user_id: UUID,
    database_session: Session = Depends(get_database)
) -> List[MediaResponse]:
    """
    Get all bookmarks for a user.

    Retrieves all PENDING media items from the user's system watchlist.
    These are items the user has bookmarked but not yet added to a specific watchlist.

    Args:
        user_id: UUID of the user whose bookmarks to retrieve
        database_session: Database session dependency

    Returns:
        List[MediaResponse]: List of bookmarked media items

    Raises:
        HTTPException: 404 if system watchlist doesn't exist
    """
    return get_user_bookmarks(user_id, database_session)


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Create a bookmark",
    description="Add a media item to the user's system watchlist as a pending bookmark",
)
def add_bookmark(
    bookmark_data: BookmarkCreate,
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> dict:
    """
    Create a new bookmark.

    Adds a media item with type PENDING to the authenticated user's system watchlist.
    The system watchlist is automatically created during user registration.

    Args:
        bookmark_data: Bookmark information including TMDB ID, title, and metadata
        current_user: Currently authenticated user
        database_session: Database session dependency

    Returns:
        dict: Success message confirming bookmark creation

    Raises:
        HTTPException: 404 if system watchlist doesn't exist
    """
    return create_bookmark(bookmark_data, current_user, database_session)


@router.delete(
    "/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a bookmark",
    description="Remove a pending media item from the user's system watchlist",
)
def remove_bookmark(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
):
    """
    Delete a bookmark.

    Removes a PENDING media item from the authenticated user's system watchlist.
    Only works for media items with type PENDING in the system watchlist.

    Args:
        media_id: UUID of the bookmark to delete
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 404 if bookmark doesn't exist
            - 403 if user doesn't own the bookmark or media is not a PENDING item
    """
    delete_bookmark(media_id, current_user, database_session)
