from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies import get_database, get_current_user
from app.models import User, Media, Watchlist
from app.schemas import MediaCreate, MediaUpdate

router = APIRouter(
    tags=["Media"],
    responses={
        404: {"description": "Media or watchlist not found"},
        403: {"description": "Access forbidden"},
    },
)


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Add media to watchlist",
    description="Add a movie or TV show to a specific watchlist (requires ownership)",
)
def add_media_to_watchlist(
    media_data: MediaCreate,
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> dict:
    """
    Add a media item to a watchlist.

    Adds a movie or TV show to the specified watchlist. The user must own
    the target watchlist to perform this action. Media data includes
    information from TMDB (The Movie Database).

    Args:
        media_data: Media information including TMDB ID, title, and metadata
        current_user: Currently authenticated user
        database_session: Database session dependency

    Returns:
        dict: Success message confirming media addition

    Raises:
        HTTPException:
            - 404 if watchlist doesn't exist
            - 403 if user doesn't own the watchlist
    """
    # Verify watchlist exists and belongs to user
    watchlist = (
        database_session.query(Watchlist)
        .filter(Watchlist.id == media_data.watchlist_id)
        .first()
    )

    if not watchlist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found"
        )

    if str(watchlist.author_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to add media to this watchlist",
        )

    new_media = Media(
        tmdb_id=media_data.tmdb_id,
        genre_ids=media_data.genre_ids,
        poster_path=media_data.poster_path,
        backdrop_path=media_data.backdrop_path,
        release_date=media_data.release_date,
        runtime=media_data.runtime,
        title=media_data.title,
        media_type=media_data.media_type,
        watchlist_id=media_data.watchlist_id,
    )

    database_session.add(new_media)
    database_session.commit()

    return {"message": "Media added successfully"}


@router.put(
    "/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update media",
    description="Update media information or move it to another watchlist",
)
def update_media(
    media_id: UUID,
    media_data: MediaUpdate,
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
):
    """
    Update media item or move it to another watchlist.

    Allows updating media information or moving it between watchlists.
    The user must own both the current and target watchlists.

    Args:
        media_id: UUID of the media item to update
        media_data: Updated media information (e.g., new watchlist_id)
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 404 if media doesn't exist
            - 403 if user doesn't own the current or target watchlist
    """
    media = database_session.query(Media).filter(Media.id == media_id).first()

    if not media:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media not found"
        )

    # Verify user owns the current watchlist
    current_watchlist = (
        database_session.query(Watchlist)
        .filter(Watchlist.id == media.watchlist_id)
        .first()
    )

    if str(current_watchlist.author_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this media",
        )

    # If moving to a new watchlist, verify ownership of target watchlist
    if media_data.watchlist_id:
        new_watchlist = (
            database_session.query(Watchlist)
            .filter(Watchlist.id == media_data.watchlist_id)
            .first()
        )

        if not new_watchlist or str(new_watchlist.author_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to move media to this watchlist",
            )

        media.watchlist_id = media_data.watchlist_id

    database_session.commit()


@router.delete(
    "/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete media from watchlist",
    description="Remove a media item from its watchlist permanently",
)
def delete_media(
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
):
    """
    Delete media item from watchlist.

    Permanently removes a media item from its watchlist. The user must own
    the watchlist containing the media item to perform this action.

    Args:
        media_id: UUID of the media item to delete
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 404 if media doesn't exist
            - 403 if user doesn't own the watchlist containing the media
    """
    media = database_session.query(Media).filter(Media.id == media_id).first()

    if not media:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media not found"
        )

    # Verify user owns the watchlist
    watchlist = (
        database_session.query(Watchlist)
        .filter(Watchlist.id == media.watchlist_id)
        .first()
    )

    if str(watchlist.author_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this media",
        )

    database_session.delete(media)
    database_session.commit()
