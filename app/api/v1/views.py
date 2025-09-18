from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Optional

from app.api.dependencies import get_database, get_current_user
from app.models import User, View
from app.schemas import ViewCreate, ViewResponse

router = APIRouter(
    tags=["Views"],
    responses={
        404: {"description": "View not found"},
        403: {"description": "Access forbidden"}
    }
)


@router.get(
    "/{user_id}",
    response_model=List[ViewResponse],
    summary="Get user viewing history",
    description="Retrieve complete viewing history for a specific user"
)
def get_user_views(
        user_id: UUID,
        database_session: Session = Depends(get_database)
) -> List[ViewResponse]:
    """
    Get all viewing history for a user.

    Retrieves the complete viewing history for the specified user,
    including all movies and TV shows they have marked as watched.

    Args:
        user_id: UUID of the user whose viewing history to retrieve
        database_session: Database session dependency

    Returns:
        List[ViewResponse]: Complete list of user's viewing history
    """
    views = database_session.query(View).filter(View.viewer_id == user_id).all()
    return [ViewResponse.model_validate(view) for view in views]


@router.get(
    "/{media_type}/{user_id}",
    response_model=List[ViewResponse],
    summary="Get filtered viewing history",
    description="Retrieve viewing history filtered by media type and optionally by genre"
)
def get_user_views_by_type(
        media_type: str,
        user_id: UUID,
        genre: Optional[int] = Query(None, description="Filter by specific genre ID"),
        database_session: Session = Depends(get_database)
) -> List[ViewResponse]:
    """
    Get user viewing history filtered by media type and genre.

    Retrieves viewing history filtered by media type (movie/tv) and
    optionally by a specific genre for more targeted results.

    Args:
        media_type: Type of media to filter by ('movie' or 'tv')
        user_id: UUID of the user whose viewing history to retrieve
        genre: Optional genre ID to filter results (e.g., 28 for Action)
        database_session: Database session dependency

    Returns:
        List[ViewResponse]: Filtered list of user's viewing history
    """
    query = database_session.query(View).filter(
        View.viewer_id == user_id,
        View.media_type == media_type
    )

    # Apply genre filter if specified
    if genre is not None:
        query = query.filter(View.genre_ids.any(genre))

    views = query.all()
    return [ViewResponse.model_validate(view) for view in views]


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Mark media as watched",
    description="Add a new viewing record for a movie or TV show"
)
def add_view(
        view_data: ViewCreate,
        current_user: User = Depends(get_current_user),
        database_session: Session = Depends(get_database)
) -> dict:
    """
    Add a new viewing record (mark media as watched).

    Records that a user has watched a specific movie or TV show.
    Users can only add viewing records for themselves.

    Args:
        view_data: Viewing record data including media information and viewer ID
        current_user: Currently authenticated user
        database_session: Database session dependency

    Returns:
        dict: Success message confirming the viewing record was added

    Raises:
        HTTPException: 403 if user tries to add viewing record for another user
    """
    # Verify user is adding view for themselves
    if str(view_data.viewer_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to add view for this user"
        )

    new_view = View(
        tmdb_id=view_data.tmdb_id,
        genre_ids=view_data.genre_ids,
        poster_path=view_data.poster_path,
        backdrop_path=view_data.backdrop_path,
        release_date=view_data.release_date,
        release_year=view_data.release_year,
        runtime=view_data.runtime,
        title=view_data.title,
        media_type=view_data.media_type,
        viewer_id=view_data.viewer_id
    )

    database_session.add(new_view)
    database_session.commit()

    return {"message": "View added successfully"}


@router.delete(
    "/{view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove viewing record",
    description="Delete a viewing record from user's history"
)
def delete_view(
        view_id: UUID,
        current_user: User = Depends(get_current_user),
        database_session: Session = Depends(get_database)
):
    """
    Delete a viewing record from user's history.

    Removes a viewing record from the user's watch history.
    Users can only delete their own viewing records.

    Args:
        view_id: UUID of the viewing record to delete
        current_user: Currently authenticated user
        database_session: Database session dependency

    Raises:
        HTTPException:
            - 404 if viewing record doesn't exist
            - 403 if user doesn't own the viewing record
    """
    view = database_session.query(View).filter(View.id == view_id).first()

    if not view:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="View not found"
        )

    # Verify user owns this viewing record
    if str(view.viewer_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this view"
        )

    database_session.delete(view)
    database_session.commit()