"""Download request API endpoints."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.models import User
from app.schemas import DownloadRequestResponse, RadarrMovieDownloadCreate
from app.services.download_request_service import (
    get_download_request_status,
    list_download_requests,
    request_radarr_movie_download,
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
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> DownloadRequestResponse:
    """Request a movie download through Radarr."""
    return request_radarr_movie_download(payload.tmdb_id, user, database_session)


@router.get(
    "",
    response_model=list[DownloadRequestResponse],
    status_code=status.HTTP_200_OK,
    summary="List download requests",
    description="Return all household download requests.",
)
def list_requests(
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> list[DownloadRequestResponse]:
    """List all household download requests."""
    return list_download_requests(database_session)


@router.get(
    "/status",
    response_model=DownloadRequestResponse | None,
    status_code=status.HTTP_200_OK,
    summary="Get download request status",
    description="Return the latest household download request for a media item.",
)
def request_status(
    tmdb_id: int = Query(..., description="TMDB media identifier"),
    media_type: str = Query("movie", description="Media type"),
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> DownloadRequestResponse | None:
    """Return download request status for one media item."""
    return get_download_request_status(tmdb_id, media_type, database_session)
