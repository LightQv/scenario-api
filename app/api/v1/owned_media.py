"""
Owned media API endpoints.

These routes expose Scenario's local owned media state and a manual Radarr sync
action. Read endpoints never call Radarr/Sonarr in real time.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.database.session import SessionLocal
from app.models import User
from app.schemas import (
    OwnedMediaResponse,
    OwnedMediaStatusResponse,
    OwnedMediaSyncStatusResponse,
)
from app.services.owned_media_service import (
    SyncAlreadyRunningError,
    get_owned_media,
    get_radarr_owned_movies_sync_status,
    get_owned_media_status,
    start_radarr_owned_movies_sync,
    sync_radarr_owned_movies_with_reserved_lock,
)

router = APIRouter(
    tags=["Owned media"],
    responses={
        403: {"description": "Access forbidden"},
        409: {"description": "Sync already running"},
        503: {"description": "Integration not configured"},
    },
)


@router.post(
    "/sync/radarr",
    response_model=OwnedMediaSyncStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync owned movies from Radarr",
    description="Queue a Radarr movie library sync and TMDB metadata hydration.",
)
def sync_radarr_owned_media(
    background_tasks: BackgroundTasks,
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> OwnedMediaSyncStatusResponse:
    """
    Manually sync Scenario's owned movies from Radarr.

    This endpoint starts background work and returns immediately. The mobile app
    should use the sync status endpoint to observe completion or failure.
    """
    try:
        sync_status = start_radarr_owned_movies_sync(database_session)
        background_tasks.add_task(_run_radarr_owned_media_sync_background)
        return sync_status
    except SyncAlreadyRunningError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


def _run_radarr_owned_media_sync_background() -> None:
    """Run queued Radarr owned movie sync with a fresh DB session."""
    database_session = SessionLocal()
    try:
        sync_radarr_owned_movies_with_reserved_lock(database_session)
    finally:
        database_session.close()


@router.get(
    "/sync/status",
    response_model=OwnedMediaSyncStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Radarr owned movies sync status",
    description="Return the current or latest Radarr movie sync status.",
)
def radarr_owned_media_sync_status(
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> OwnedMediaSyncStatusResponse:
    """
    Return Radarr movie sync state for profile/admin UI controls.
    """
    return get_radarr_owned_movies_sync_status(database_session)


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
