"""Download request API endpoints."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.models import User
from app.schemas import (
    DownloadRequestResponse,
    RadarrMovieDownloadCreate,
    SonarrSeasonDownloadCreate,
    SonarrSeriesDownloadCreate,
)
from app.services.download_request_service import (
    cancel_all_download_requests,
    cancel_download_request,
    clean_download_requests,
    get_download_request_status,
    list_download_requests,
    request_radarr_movie_download,
    request_sonarr_season_download,
    request_sonarr_series_download,
    retry_download_request,
)

router = APIRouter(
    tags=["Downloads"],
    responses={
        403: {"description": "Access forbidden"},
        502: {"description": "Radarr request failed"},
        503: {"description": "Integration not configured"},
    },
)


@router.post(
    "/radarr/movies",
    response_model=DownloadRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a Radarr movie download",
    description="Add a movie to Radarr and trigger automatic search.",
)
def request_radarr_movie(
    payload: RadarrMovieDownloadCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> DownloadRequestResponse:
    """Request a movie download through Radarr."""
    return request_radarr_movie_download(
        payload.tmdb_id,
        user,
        database_session,
        background_tasks,
    )


@router.post(
    "/sonarr/series",
    response_model=DownloadRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a Sonarr series download",
    description="Add a TV series to Sonarr and trigger automatic search.",
)
def request_sonarr_series(
    payload: SonarrSeriesDownloadCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> DownloadRequestResponse:
    """Request a whole TV series download through Sonarr."""
    return request_sonarr_series_download(
        payload.tmdb_id,
        user,
        database_session,
        background_tasks,
    )


@router.post(
    "/sonarr/seasons",
    response_model=DownloadRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a Sonarr season download",
    description="Add a TV series to Sonarr if needed and trigger season search.",
)
def request_sonarr_season(
    payload: SonarrSeasonDownloadCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> DownloadRequestResponse:
    """Request one TV season download through Sonarr."""
    return request_sonarr_season_download(
        payload.tmdb_id,
        payload.season_number,
        user,
        database_session,
        background_tasks,
    )


@router.get(
    "",
    response_model=list[DownloadRequestResponse],
    status_code=status.HTTP_200_OK,
    summary="List download requests",
    description="Return the current user's download requests.",
)
def list_requests(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> list[DownloadRequestResponse]:
    """List all download requests for the current user."""
    return list_download_requests(database_session, user.id)


@router.delete(
    "/clean",
    response_model=dict[str, int],
    status_code=status.HTTP_200_OK,
    summary="Clean terminal download requests",
    description="Remove local history rows for available, failed, not-found, and cancelled requests.",
)
def clean_requests(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> dict[str, int]:
    """Clean non-active download request history for the current user."""
    return {"deleted_count": clean_download_requests(database_session, user.id)}


@router.post(
    "/cancel-all",
    response_model=dict[str, int],
    status_code=status.HTTP_200_OK,
    summary="Cancel all active download requests",
    description="Cancel the current user's active download requests and remove matching integration queue state.",
)
def cancel_all_requests(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> dict[str, int]:
    """Cancel all cancellable download requests for the current user."""
    return {"cancelled_count": cancel_all_download_requests(database_session, user.id)}


@router.post(
    "/{request_id}/retry",
    response_model=DownloadRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Retry a download request",
    description="Retry a failed, not-found, or cancelled download request.",
)
def retry_request(
    request_id: UUID,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> DownloadRequestResponse:
    """Retry one download request owned by the current user."""
    return retry_download_request(request_id, user.id, database_session)


@router.post(
    "/{request_id}/cancel",
    response_model=DownloadRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a download request",
    description="Cancel a request and remove matching active integration queue state.",
)
def cancel_request(
    request_id: UUID,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> DownloadRequestResponse:
    """Cancel one download request owned by the current user."""
    return cancel_download_request(request_id, user.id, database_session)


@router.get(
    "/status",
    response_model=DownloadRequestResponse | None,
    status_code=status.HTTP_200_OK,
    summary="Get download request status",
    description="Return the current user's latest download request for a media item.",
)
def request_status(
    tmdb_id: int = Query(..., description="TMDB media identifier"),
    media_type: str = Query("movie", description="Media type"),
    scope: str | None = Query(None, description="Request scope for TV"),
    season_number: int | None = Query(None, description="Season number for season scope"),
    episode_number: int | None = Query(None, description="Episode number for episode scope"),
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> DownloadRequestResponse | None:
    """Return download request status for one media item."""
    return get_download_request_status(
        tmdb_id,
        media_type,
        user.id,
        database_session,
        scope,
        season_number,
        episode_number,
    )
