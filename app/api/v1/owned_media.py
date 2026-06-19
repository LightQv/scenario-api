"""
Owned media API endpoints.

These routes expose Scenario's local owned media state and a manual Radarr sync
action. Read endpoints never call Radarr/Sonarr in real time.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.models import User
from app.schemas import (
    OwnedMediaResponse,
    OwnedMediaStatusResponse,
    OwnedMediaSyncResponse,
)
from app.services.owned_media_service import (
    get_owned_media,
    get_owned_media_status,
    sync_radarr_owned_movies,
)

router = APIRouter(
    tags=["Owned media"],
    responses={
        403: {"description": "Access forbidden"},
        503: {"description": "Integration not configured"},
    },
)


@router.post(
    "/sync/radarr",
    response_model=OwnedMediaSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync owned movies from Radarr",
    description="Fetch Radarr's local movie library and store owned movie TMDB IDs.",
)
def sync_radarr_owned_media(
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> OwnedMediaSyncResponse:
    """
    Manually sync Scenario's owned movies from Radarr.

    This endpoint is intended for profile/settings actions and future cron jobs.
    It calls Radarr, then reconciles Scenario's local owned media table.
    """
    return sync_radarr_owned_movies(database_session)


@router.get(
    "",
    response_model=list[OwnedMediaResponse],
    summary="List owned media",
    description="Return all owned media rows stored in Scenario's database.",
)
def list_owned_media(
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> list[OwnedMediaResponse]:
    """
    List owned media from Scenario's database.

    This endpoint does not call Radarr or Sonarr. It is safe for the mobile app
    to use for app-wide owned media state.
    """
    return get_owned_media(database_session)


@router.get(
    "/status",
    response_model=OwnedMediaStatusResponse,
    summary="Get owned media status",
    description="Check if a specific TMDB media is stored as owned locally.",
)
def owned_media_status(
    tmdb_id: int = Query(..., description="TMDB media identifier"),
    media_type: str = Query(..., description="Media type, e.g. movie or tv"),
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> OwnedMediaStatusResponse:
    """
    Check whether a media is owned using Scenario's database only.
    """
    return get_owned_media_status(tmdb_id, media_type, database_session)
