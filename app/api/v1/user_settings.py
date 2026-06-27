"""User settings API endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_database
from app.models import User
from app.schemas import (
    DownloadSettingsOverview,
    RadarrOptionsResponse,
    RadarrSettingsPatch,
    RadarrSettingsResponse,
    SonarrOptionsResponse,
    SonarrProfileType,
    SonarrProfileUpsert,
    SonarrSettingsPatch,
    SonarrSettingsResponse,
    TestConnectionResponse,
)
from app.services.user_integration_settings_service import (
    get_download_settings_overview,
    get_radarr_options,
    get_radarr_settings,
    get_sonarr_options,
    get_sonarr_settings,
    delete_sonarr_profile,
    test_radarr_connection,
    test_sonarr_connection,
    update_radarr_settings,
    update_sonarr_settings,
    upsert_sonarr_profile,
)

router = APIRouter(
    tags=["User settings"],
    responses={
        403: {"description": "Access forbidden"},
        409: {"description": "Integration disabled or not configured"},
        502: {"description": "Integration request failed"},
        503: {"description": "Encryption key not configured"},
    },
)


@router.get(
    "/downloads",
    response_model=DownloadSettingsOverview,
    status_code=status.HTTP_200_OK,
    summary="Get download integration settings overview",
)
def download_settings_overview(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> DownloadSettingsOverview:
    """Return masked Radarr and Sonarr settings status for the current user."""
    return get_download_settings_overview(database_session, user.id)


@router.get(
    "/downloads/radarr",
    response_model=RadarrSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Radarr settings",
)
def radarr_settings(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> RadarrSettingsResponse:
    """Return masked Radarr settings for the current user."""
    return get_radarr_settings(database_session, user.id)


@router.patch(
    "/downloads/radarr",
    response_model=RadarrSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Radarr settings",
)
def patch_radarr_settings(
    payload: RadarrSettingsPatch,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> RadarrSettingsResponse:
    """Patch Radarr settings without contacting Radarr."""
    return update_radarr_settings(database_session, user.id, payload)


@router.post(
    "/downloads/radarr/test",
    response_model=TestConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Test Radarr connection",
)
def test_radarr(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> TestConnectionResponse:
    """Explicitly test the current user's Radarr connection."""
    return test_radarr_connection(database_session, user.id)


@router.get(
    "/downloads/radarr/options",
    response_model=RadarrOptionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Radarr selectable options",
)
def radarr_options(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> RadarrOptionsResponse:
    """Fetch live Radarr profile/root-folder options for the current user."""
    return get_radarr_options(database_session, user.id)


@router.get(
    "/downloads/sonarr",
    response_model=SonarrSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Sonarr settings",
)
def sonarr_settings(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> SonarrSettingsResponse:
    """Return masked Sonarr settings for the current user."""
    return get_sonarr_settings(database_session, user.id)


@router.patch(
    "/downloads/sonarr",
    response_model=SonarrSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Sonarr settings",
)
def patch_sonarr_settings(
    payload: SonarrSettingsPatch,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> SonarrSettingsResponse:
    """Patch Sonarr settings without contacting Sonarr."""
    return update_sonarr_settings(database_session, user.id, payload)


@router.put(
    "/downloads/sonarr/profiles/{profile_type}",
    response_model=SonarrSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or replace a Sonarr Scenario profile",
)
def put_sonarr_profile(
    profile_type: SonarrProfileType,
    payload: SonarrProfileUpsert,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> SonarrSettingsResponse:
    """Create or replace one grouped Sonarr profile for the current user."""
    return upsert_sonarr_profile(database_session, user.id, profile_type, payload)


@router.delete(
    "/downloads/sonarr/profiles/{profile_type}",
    response_model=SonarrSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a Sonarr Scenario profile",
)
def remove_sonarr_profile(
    profile_type: SonarrProfileType,
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> SonarrSettingsResponse:
    """Delete one grouped Sonarr profile for the current user."""
    return delete_sonarr_profile(database_session, user.id, profile_type)


@router.post(
    "/downloads/sonarr/test",
    response_model=TestConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Test Sonarr connection",
)
def test_sonarr(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> TestConnectionResponse:
    """Explicitly test the current user's Sonarr connection."""
    return test_sonarr_connection(database_session, user.id)


@router.get(
    "/downloads/sonarr/options",
    response_model=SonarrOptionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Sonarr selectable options",
)
def sonarr_options(
    user: User = Depends(get_current_user),
    database_session: Session = Depends(get_database),
) -> SonarrOptionsResponse:
    """Fetch live Sonarr profile/root-folder/tag options for the current user."""
    return get_sonarr_options(database_session, user.id)
