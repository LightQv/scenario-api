from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from typing import List, Optional

from app.api.dependencies import get_database, get_current_user
from app.models import User, Watchlist, Media
from app.models.enums import WatchlistType
from app.schemas import (
    WatchlistCreate,
    WatchlistUpdate,
    WatchlistResponse,
    WatchlistDetail,
    MediaResponse,
)

router = APIRouter(
    tags=["Watchlists"],
    responses={
        404: {"description": "Watchlist not found"},
        403: {"description": "Access forbidden"},
    },
)


@router.get(
    "/{user_id}",
    response_model=List[WatchlistResponse],
    summary="Get user watchlists",
    description="Retrieve all watchlists created by a specific user with media counts",
)
def get_user_watchlists(
    user_id: UUID, database_session: Session = Depends(get_database)
) -> List[WatchlistResponse]:
    """
    Get all watchlists for a specific user.

    Retrieves all watchlists created by the specified user, including
    the count of media items in each watchlist and a summary of media IDs.

    Args:
        user_id: UUID of the user whose watchlists to retrieve
        database_session: Database session dependency

    Returns:
        List[WatchlistResponse]: List of user's watchlists with media counts
    """
    watchlists = (
        database_session.query(
            Watchlist.id,
            Watchlist.title,
            Watchlist.type,
            Watchlist.author_id,
            func.count(Media.id).label("medias_count"),
        )
        .outerjoin(Media, Watchlist.id == Media.watchlist_id)
        .filter(Watchlist.author_id == user_id)
        .group_by(Watchlist.id, Watchlist.title, Watchlist.type, Watchlist.author_id)
        .all()
    )

    result = []
    for watchlist_data in watchlists:
        # Get media items for each watchlist
        medias = (
            database_session.query(Media.id, Media.tmdb_id)
            .filter(Media.watchlist_id == watchlist_data.id)
            .all()
        )

        watchlist_response = WatchlistResponse(
            id=watchlist_data.id,
            title=watchlist_data.title,
            type=watchlist_data.type,
            author_id=watchlist_data.author_id,
            medias=[{"id": media.id, "tmdb_id": media.tmdb_id} for media in medias],
            medias_count=watchlist_data.medias_count or 0,
        )
        result.append(watchlist_response)

    return result


@router.get(
    "/detail/{watchlist_id}",
    response_model=WatchlistDetail,
    summary="Get watchlist details",
    description="Retrieve detailed information about a watchlist including all media items",
)
def get_watchlist_details(
    watchlist_id: UUID,
    genre: Optional[str] = Query(None, description="Filter media by genre ID"),
    database_session: Session = Depends(get_database),
) -> WatchlistDetail:
    """
    Get detailed watchlist information with all media items.

    Retrieves complete watchlist details including all media items.
    Optionally filters media by genre for more targeted results.

    Args:
        watchlist_id: UUID of the watchlist to retrieve
        genre: Optional genre ID to filter media items
        database_session: Database session dependency

    Returns:
        WatchlistDetail: Complete watchlist information with media items

    Raises:
        HTTPException: 404 if watchlist doesn't exist
    """
    watchlist = (
        database_session.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    )

    if not watchlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found"
        )

    # Build media query
    media_query = database_session.query(Media).filter(
        Media.watchlist_id == watchlist_id
    )

    # Apply genre filter if specified
    if genre is not None:
        media_query = media_query.filter(Media.genre_ids.any(genre))

    medias = media_query.all()

    # Count total media items (without genre filter)
    total_medias_count = (
        database_session.query(func.count(Media.id))
        .filter(Media.watchlist_id == watchlist_id)
        .scalar()
    )

    return WatchlistDetail(
        title=watchlist.title,
        type=watchlist.type,
        medias=[MediaResponse.model_validate(media) for media in medias],
        medias_count=total_medias_count,
    )


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Create new watchlist",
    description="Create a new watchlist for the authenticated user",
)
def create_watchlist(
    watchlist_data: WatchlistCreate,
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> dict:
    """
    Create a new watchlist for the authenticated user.

    Creates a new empty watchlist owned by the currently authenticated user.
    Media items can be added to the watchlist using the media endpoints.

    Args:
        watchlist_data: Watchlist creation data (title)
        current_user: Currently authenticated user
        database_session: Database session dependency

    Returns:
        dict: Success message confirming watchlist creation
    """
    new_watchlist = Watchlist(title=watchlist_data.title, author_id=current_user.id)

    database_session.add(new_watchlist)
    database_session.commit()

    return {"message": "Watchlist created successfully"}


@router.put(
    "/{watchlist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update watchlist",
    description="Update watchlist information (requires ownership)",
)
def update_watchlist(
    watchlist_id: UUID,
    watchlist_data: WatchlistUpdate,
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
):
    """
    Update watchlist information.

    Allows the watchlist owner to update watchlist properties such as title.
    Only the watchlist owner can perform this action.

    Args:
        watchlist_id: UUID of the watchlist to update
        watchlist_data: Updated watchlist data
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 404 if watchlist doesn't exist
            - 403 if user doesn't own the watchlist
    """
    watchlist = (
        database_session.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    )

    if not watchlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found"
        )

    # Verify watchlist ownership
    if str(watchlist.author_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this watchlist",
        )

    # Prevent modification of SYSTEM watchlists
    if watchlist.type == WatchlistType.SYSTEM.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify system watchlists",
        )

    # Update provided fields
    update_data = watchlist_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(watchlist, field, value)

    database_session.commit()


@router.delete(
    "/{watchlist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete watchlist",
    description="Permanently delete watchlist and all associated media (requires ownership)",
)
def delete_watchlist(
    watchlist_id: UUID,
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
):
    """
    Delete watchlist and all associated media items.

    Permanently deletes the watchlist and all media items contained within it.
    This action is irreversible and can only be performed by the watchlist owner.

    Args:
        watchlist_id: UUID of the watchlist to delete
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 404 if watchlist doesn't exist
            - 403 if user doesn't own the watchlist
    """
    watchlist = (
        database_session.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    )

    if not watchlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found"
        )

    # Verify watchlist ownership
    if str(watchlist.author_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this watchlist",
        )

    # Prevent deletion of SYSTEM watchlists
    if watchlist.type == WatchlistType.SYSTEM.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete system watchlists",
        )

    database_session.delete(watchlist)
    database_session.commit()
