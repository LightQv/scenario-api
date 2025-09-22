from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from typing import List

from app.api.dependencies import get_database
from app.models import View
from app.schemas import ViewCountByType, ViewCountByYear, ViewRuntime

router = APIRouter(
    tags=["Statistics"],
    responses={
        404: {"description": "No statistics found"}
    }
)


@router.get(
    "/count/{media_type}/{user_id}",
    response_model=List[ViewCountByType],
    summary="Get viewing count by media type",
    description="Get the number of movies or TV shows watched by a user"
)
def get_view_count_by_type(
        media_type: str,
        user_id: UUID,
        database_session: Session = Depends(get_database)
) -> List[ViewCountByType]:
    """
    Get viewing statistics by media type for a user.

    Returns the total count of movies or TV shows watched by the specified user.
    This helps understand user viewing preferences between different media types.

    Args:
        media_type: Type of media to count ('movie' or 'tv')
        user_id: UUID of the user whose statistics to retrieve
        database_session: Database session dependency

    Returns:
        List[ViewCountByType]: Statistics showing count by media type
    """
    results = database_session.query(
        View.media_type,
        func.count(View.id).label('count')
    ).filter(
        View.viewer_id == user_id,
        View.media_type == media_type
    ).group_by(View.media_type).all()

    return [
        ViewCountByType(media_type=result.media_type, count=result.count)
        for result in results
    ]


@router.get(
    "/year/{media_type}/{user_id}",
    response_model=List[ViewCountByYear],
    summary="Get viewing count by release year",
    description="Get viewing statistics grouped by media release year"
)
def get_view_count_by_year(
        media_type: str,
        user_id: UUID,
        database_session: Session = Depends(get_database)
) -> List[ViewCountByYear]:
    """
    Get viewing statistics by release year for a user.

    Returns viewing statistics grouped by the release year of watched content.
    This helps identify user preferences for content from different time periods.

    Args:
        media_type: Type of media to analyze ('movie' or 'tv')
        user_id: UUID of the user whose statistics to retrieve
        database_session: Database session dependency

    Returns:
        List[ViewCountByYear]: Statistics showing count by release year, ordered chronologically
    """
    results = database_session.query(
        View.release_year,
        func.count(View.id).label('count')
    ).filter(
        View.viewer_id == user_id,
        View.media_type == media_type
    ).group_by(View.release_year).order_by(View.release_year.asc()).all()

    return [
        ViewCountByYear(release_year=result.release_year, count=result.count)
        for result in results
    ]


@router.get(
    "/runtime/{media_type}/{user_id}",
    response_model=List[ViewRuntime],
    summary="Get runtime statistics",
    description="Get runtime information for all media watched by a user"
)
def get_runtime_by_user(
        media_type: str,
        user_id: UUID,
        database_session: Session = Depends(get_database)
) -> List[ViewRuntime]:
    """
    Get runtime statistics for all media watched by a user.

    Returns the runtime (duration) of all movies or TV show episodes
    watched by the user. This can be used to calculate total watch time
    or analyze viewing duration preferences.

    Args:
        media_type: Type of media to analyze ('movie' or 'tv')
        user_id: UUID of the user whose statistics to retrieve
        database_session: Database session dependency

    Returns:
        List[ViewRuntime]: List of runtime values for all watched media
    """
    results = database_session.query(View.runtime).filter(
        View.viewer_id == user_id,
        View.media_type == media_type
    ).all()

    return [ViewRuntime(runtime=result.runtime) for result in results]