"""
Owned media API endpoints.

These routes expose Scenario's local owned media state and a manual Radarr sync
action. Read endpoints never call Radarr/Sonarr in real time.
"""

from secrets import compare_digest

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.core.settings import settings
from app.database.session import SessionLocal
from app.models import User
from app.schemas import (
    OwnedMediaResponse,
    OwnedMediaStatusResponse,
    OwnedMediaSyncStatusResponse,
    RadarrWebhookPayload,
    RadarrWebhookResponse,
    SonarrWebhookPayload,
    SonarrWebhookResponse,
    TvAvailabilityResponse,
    TvSeasonAvailabilityResponse,
)
from app.services.owned_media_service import (
    SyncAlreadyRunningError,
    get_owned_media,
    get_radarr_owned_movies_sync_status,
    get_owned_media_sync_status,
    get_owned_media_status,
    get_tv_availability_status,
    get_tv_season_availability_status,
    handle_radarr_webhook,
    handle_sonarr_webhook,
    start_radarr_owned_movies_sync,
    start_sonarr_owned_tv_sync,
    sync_radarr_owned_movies_with_reserved_lock,
    sync_sonarr_owned_tv_with_reserved_lock,
)
from app.services.radarr_service import RadarrService
from app.services.sonarr_service import SonarrService
from app.services.user_integration_settings_service import (
    get_enabled_radarr_config,
    get_enabled_sonarr_config,
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
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> OwnedMediaSyncStatusResponse:
    """
    Manually sync Scenario's owned movies from Radarr.

    This endpoint starts background work and returns immediately. The mobile app
    should use the sync status endpoint to observe completion or failure.
    """
    try:
        get_enabled_radarr_config(database_session, user.id)
        sync_status = start_radarr_owned_movies_sync(database_session)
        background_tasks.add_task(_run_radarr_owned_media_sync_background, user.id)
        return sync_status
    except SyncAlreadyRunningError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


def _run_radarr_owned_media_sync_background(user_id) -> None:
    """Run queued Radarr owned movie sync with a fresh DB session."""
    database_session = SessionLocal()
    try:
        runtime_config = get_enabled_radarr_config(database_session, user_id)
        radarr_service = RadarrService(
            url=runtime_config.config.get("url"),
            api_key=runtime_config.api_key,
            root_folder_path=runtime_config.config.get("root_folder_path"),
            quality_profile_id=runtime_config.config.get("quality_profile_id"),
        )
        sync_radarr_owned_movies_with_reserved_lock(database_session, radarr_service=radarr_service)
    finally:
        database_session.close()


@router.post(
    "/sync/sonarr",
    response_model=OwnedMediaSyncStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync owned TV episodes from Sonarr",
    description="Queue a Sonarr TV library sync and TMDB metadata hydration.",
)
def sync_sonarr_owned_media(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> OwnedMediaSyncStatusResponse:
    """Manually sync Scenario's owned TV episodes from Sonarr."""
    try:
        get_enabled_sonarr_config(database_session, user.id)
        sync_status = start_sonarr_owned_tv_sync(database_session)
        background_tasks.add_task(_run_sonarr_owned_media_sync_background, user.id)
        return sync_status
    except SyncAlreadyRunningError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


def _run_sonarr_owned_media_sync_background(user_id) -> None:
    """Run queued Sonarr owned TV sync with a fresh DB session."""
    database_session = SessionLocal()
    try:
        runtime_config = get_enabled_sonarr_config(database_session, user_id)
        sonarr_service = SonarrService(
            url=runtime_config.config.get("url"),
            api_key=runtime_config.api_key,
            root_folder_path=runtime_config.config.get("root_folder_path"),
            anime_root_folder_path=runtime_config.config.get("anime_root_folder_path"),
            quality_profile_id=runtime_config.config.get("quality_profile_id"),
            on_air_quality_profile_id=runtime_config.config.get("on_air_quality_profile_id"),
            complete_quality_profile_id=runtime_config.config.get("complete_quality_profile_id"),
            anime_quality_profile_id=runtime_config.config.get("anime_quality_profile_id"),
            language_profile_id=runtime_config.config.get("language_profile_id"),
            anime_language_profile_id=runtime_config.config.get("anime_language_profile_id"),
            series_type=runtime_config.config.get("series_type"),
            anime_series_type=runtime_config.config.get("anime_series_type"),
            monitor_mode=runtime_config.config.get("monitor_mode"),
            season_folder=runtime_config.config.get("season_folder"),
            use_anime_series_type=runtime_config.config.get("use_anime_series_type"),
        )
        sync_sonarr_owned_tv_with_reserved_lock(database_session, sonarr_service=sonarr_service)
    finally:
        database_session.close()


@router.post(
    "/webhooks/radarr",
    response_model=RadarrWebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Handle Radarr owned media webhook",
    description="Receive Radarr movie availability events and update owned media.",
    responses={403: {"description": "Invalid webhook token"}},
)
def radarr_owned_media_webhook(
    payload: RadarrWebhookPayload,
    token: str = Query(..., description="Radarr webhook shared secret"),
    database_session: Session = Depends(get_database),
) -> RadarrWebhookResponse:
    """
    Handle Radarr webhook events without Scenario user authentication.

    Radarr uses this endpoint to notify Scenario when a movie file is imported
    or removed. The shared token protects the endpoint from unauthenticated
    public writes while keeping Radarr configuration simple.
    """
    if not compare_digest(token, settings.RADARR_WEBHOOK_SECRET):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook token",
        )

    return handle_radarr_webhook(payload, database_session)


@router.post(
    "/webhooks/sonarr",
    response_model=SonarrWebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Handle Sonarr owned media webhook",
    description="Receive Sonarr TV availability events and update owned media.",
    responses={403: {"description": "Invalid webhook token"}},
)
def sonarr_owned_media_webhook(
    payload: SonarrWebhookPayload,
    token: str = Query(..., description="Sonarr webhook shared secret"),
    database_session: Session = Depends(get_database),
) -> SonarrWebhookResponse:
    """Handle Sonarr webhook events without Scenario user authentication."""
    if not compare_digest(token, settings.SONARR_WEBHOOK_SECRET):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook token",
        )

    return handle_sonarr_webhook(payload, database_session)


@router.get(
    "/sync/status",
    response_model=OwnedMediaSyncStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Radarr owned movies sync status",
    description="Return the current or latest Radarr movie sync status.",
)
def radarr_owned_media_sync_status(
    source: str = Query("RADARR", description="Integration source"),
    media_type: str = Query("movie", description="Synced media type"),
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> OwnedMediaSyncStatusResponse:
    """
    Return Radarr movie sync state for profile/admin UI controls.
    """
    if source == "RADARR" and media_type == "movie":
        return get_radarr_owned_movies_sync_status(database_session)
    return get_owned_media_sync_status(database_session, source, media_type)


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
    summary="Get generic owned media status",
    description="Check local ownership for movies or derived local TV availability.",
)
def owned_media_status(
    tmdb_id: int = Query(..., description="TMDB media identifier"),
    media_type: str = Query(..., description="Media type, e.g. movie or tv"),
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> OwnedMediaStatusResponse:
    """
    Check whether a media is owned using Scenario's database only.

    Movies return a direct Radarr-owned boolean. TV shows return derived Sonarr
    availability from locally synced owned episodes.
    """
    return get_owned_media_status(tmdb_id, media_type, database_session)


@router.get(
    "/tv/status",
    response_model=TvAvailabilityResponse,
    summary="Get TV series availability",
    description="Return derived TV availability from locally synced Sonarr episodes.",
)
def tv_availability_status(
    tmdb_id: int = Query(..., description="TMDB TV series identifier"),
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> TvAvailabilityResponse:
    """Return TV series availability using local ownership and TMDB episode data."""
    return get_tv_availability_status(tmdb_id, database_session)


@router.get(
    "/tv/season/status",
    response_model=TvSeasonAvailabilityResponse,
    summary="Get TV season availability",
    description="Return derived TV season availability from locally synced episodes.",
)
def tv_season_availability_status(
    tmdb_id: int = Query(..., description="TMDB TV series identifier"),
    season_number: int = Query(..., ge=1, description="Regular season number"),
    _: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> TvSeasonAvailabilityResponse:
    """Return TV season availability using local ownership and TMDB episode data."""
    return get_tv_season_availability_status(tmdb_id, season_number, database_session)
