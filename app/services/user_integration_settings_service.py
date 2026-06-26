"""Per-user Radarr/Sonarr integration settings service."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import UserIntegrationSettings
from app.schemas import (
    DownloadSettingsOverview,
    IntegrationSummary,
    RadarrOptionsResponse,
    RadarrSettingsPatch,
    RadarrSettingsResponse,
    SelectOption,
    SonarrOptionsResponse,
    SonarrSettingsPatch,
    SonarrSettingsResponse,
    TestConnectionResponse,
)
from app.services.encryption_service import IntegrationSecretCipher

RADARR_SOURCE = "RADARR"
SONARR_SOURCE = "SONARR"
SECRET_API_KEY = "api_key"
SECRET_WEBHOOK_SECRET = "webhook_secret"

RADARR_CONFIG_KEYS = {
    "url",
    "root_folder_path",
    "quality_profile_id",
}
SONARR_CONFIG_KEYS = {
    "url",
    "root_folder_path",
    "anime_root_folder_path",
    "quality_profile_id",
    "on_air_quality_profile_id",
    "complete_quality_profile_id",
    "anime_quality_profile_id",
    "language_profile_id",
    "anime_language_profile_id",
    "series_type",
    "anime_series_type",
    "monitor_mode",
    "on_air_recency_days",
    "season_folder",
    "anime_tag_label",
    "on_air_tag_label",
    "complete_tag_label",
    "use_anime_series_type",
}


@dataclass(frozen=True)
class IntegrationRuntimeConfig:
    """Decrypted runtime configuration for an enabled integration."""

    source: str
    config: dict[str, Any]
    api_key: str
    webhook_secret: str | None = None


def get_download_settings_overview(
    database_session: Session,
    user_id: UUID,
) -> DownloadSettingsOverview:
    """Return masked Radarr/Sonarr settings overview for one user."""
    radarr = _get_or_create_settings(database_session, user_id, RADARR_SOURCE)
    sonarr = _get_or_create_settings(database_session, user_id, SONARR_SOURCE)
    database_session.commit()
    return DownloadSettingsOverview(
        radarr=_summary(radarr, _radarr_configured(radarr)),
        sonarr=_summary(sonarr, _sonarr_configured(sonarr)),
    )


def get_radarr_settings(database_session: Session, user_id: UUID) -> RadarrSettingsResponse:
    """Return masked Radarr settings for one user."""
    row = _get_or_create_settings(database_session, user_id, RADARR_SOURCE)
    database_session.commit()
    return _radarr_response(row)


def update_radarr_settings(
    database_session: Session,
    user_id: UUID,
    payload: RadarrSettingsPatch,
) -> RadarrSettingsResponse:
    """Patch Radarr settings without contacting Radarr."""
    row = _get_or_create_settings(database_session, user_id, RADARR_SOURCE)
    _apply_patch(row, payload.model_dump(exclude_unset=True), RADARR_CONFIG_KEYS)
    database_session.commit()
    database_session.refresh(row)
    return _radarr_response(row)


def get_sonarr_settings(database_session: Session, user_id: UUID) -> SonarrSettingsResponse:
    """Return masked Sonarr settings for one user."""
    row = _get_or_create_settings(database_session, user_id, SONARR_SOURCE)
    database_session.commit()
    return _sonarr_response(row)


def update_sonarr_settings(
    database_session: Session,
    user_id: UUID,
    payload: SonarrSettingsPatch,
) -> SonarrSettingsResponse:
    """Patch Sonarr settings without contacting Sonarr."""
    row = _get_or_create_settings(database_session, user_id, SONARR_SOURCE)
    _apply_patch(row, payload.model_dump(exclude_unset=True), SONARR_CONFIG_KEYS)
    database_session.commit()
    database_session.refresh(row)
    return _sonarr_response(row)


def get_enabled_radarr_config(
    database_session: Session,
    user_id: UUID,
) -> IntegrationRuntimeConfig:
    """Return decrypted Radarr config or raise a controlled disabled/config error."""
    row = _get_existing_settings(database_session, user_id, RADARR_SOURCE)
    if row is None or not row.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Radarr integration is disabled",
        )
    if not _radarr_configured(row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Radarr integration is not configured",
        )
    return _runtime_config(row)


def get_enabled_radarr_connection_config(
    database_session: Session,
    user_id: UUID,
) -> IntegrationRuntimeConfig:
    """Return decrypted Radarr URL/API key config for test and option loading."""
    row = _get_existing_settings(database_session, user_id, RADARR_SOURCE)
    if row is None or not row.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Radarr integration is disabled",
        )
    if not _connection_configured(row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Radarr URL and API key are required",
        )
    return _runtime_config(row)


def get_enabled_sonarr_config(
    database_session: Session,
    user_id: UUID,
) -> IntegrationRuntimeConfig:
    """Return decrypted Sonarr config or raise a controlled disabled/config error."""
    row = _get_existing_settings(database_session, user_id, SONARR_SOURCE)
    if row is None or not row.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sonarr integration is disabled",
        )
    if not _sonarr_configured(row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sonarr integration is not configured",
        )
    return _runtime_config(row)


def get_enabled_sonarr_connection_config(
    database_session: Session,
    user_id: UUID,
) -> IntegrationRuntimeConfig:
    """Return decrypted Sonarr URL/API key config for test and option loading."""
    row = _get_existing_settings(database_session, user_id, SONARR_SOURCE)
    if row is None or not row.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sonarr integration is disabled",
        )
    if not _connection_configured(row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sonarr URL and API key are required",
        )
    return _runtime_config(row)


def get_radarr_options(database_session: Session, user_id: UUID) -> RadarrOptionsResponse:
    """Fetch live Radarr option lists for picker rows."""
    runtime_config = get_enabled_radarr_connection_config(database_session, user_id)
    url = _required_str(runtime_config.config.get("url"), "Radarr URL is missing")
    quality_profiles = _arr_request(url, runtime_config.api_key, "/qualityprofile")
    root_folders = _arr_request(url, runtime_config.api_key, "/rootfolder")
    return RadarrOptionsResponse(
        quality_profiles=[
            SelectOption(label=str(item.get("name") or item.get("id")), value=int(item["id"]))
            for item in quality_profiles
            if isinstance(item, dict) and item.get("id") is not None
        ],
        root_folders=[
            SelectOption(
                label=str(item.get("path") or ""),
                value=str(item.get("path") or ""),
                meta={"free_space": item.get("freeSpace")},
            )
            for item in root_folders
            if isinstance(item, dict) and item.get("path")
        ],
    )


def get_sonarr_options(database_session: Session, user_id: UUID) -> SonarrOptionsResponse:
    """Fetch live Sonarr option lists for picker rows."""
    runtime_config = get_enabled_sonarr_connection_config(database_session, user_id)
    url = _required_str(runtime_config.config.get("url"), "Sonarr URL is missing")
    quality_profiles = _arr_request(url, runtime_config.api_key, "/qualityprofile")
    language_profiles = _safe_arr_request(url, runtime_config.api_key, "/languageprofile")
    root_folders = _arr_request(url, runtime_config.api_key, "/rootfolder")
    tags = _arr_request(url, runtime_config.api_key, "/tag")
    return SonarrOptionsResponse(
        quality_profiles=[
            SelectOption(label=str(item.get("name") or item.get("id")), value=int(item["id"]))
            for item in quality_profiles
            if isinstance(item, dict) and item.get("id") is not None
        ],
        language_profiles=[
            SelectOption(label=str(item.get("name") or item.get("id")), value=int(item["id"]))
            for item in language_profiles
            if isinstance(item, dict) and item.get("id") is not None
        ],
        root_folders=[
            SelectOption(label=str(item.get("path") or ""), value=str(item.get("path") or ""))
            for item in root_folders
            if isinstance(item, dict) and item.get("path")
        ],
        tags=[
            SelectOption(label=str(item.get("label") or ""), value=str(item.get("label") or ""))
            for item in tags
            if isinstance(item, dict) and item.get("label")
        ],
        series_types=[
            SelectOption(label="Standard", value="standard"),
            SelectOption(label="Daily", value="daily"),
            SelectOption(label="Anime", value="anime"),
        ],
        monitor_modes=[
            SelectOption(label="All episodes", value="all"),
            SelectOption(label="Future episodes", value="future"),
            SelectOption(label="Missing episodes", value="missing"),
            SelectOption(label="Existing episodes", value="existing"),
            SelectOption(label="First season", value="firstSeason"),
            SelectOption(label="Latest season", value="latestSeason"),
            SelectOption(label="None", value="none"),
        ],
    )


def test_radarr_connection(database_session: Session, user_id: UUID) -> TestConnectionResponse:
    """Explicitly test Radarr connectivity for the current user."""
    runtime_config = get_enabled_radarr_connection_config(database_session, user_id)
    payload = _arr_request(
        _required_str(runtime_config.config.get("url"), "Radarr URL is missing"),
        runtime_config.api_key,
        "/system/status",
        expect_list=False,
    )
    return TestConnectionResponse(
        ok=True,
        name=str(payload.get("appName") or "Radarr") if isinstance(payload, dict) else "Radarr",
        version=str(payload.get("version")) if isinstance(payload, dict) else None,
    )


def test_sonarr_connection(database_session: Session, user_id: UUID) -> TestConnectionResponse:
    """Explicitly test Sonarr connectivity for the current user."""
    runtime_config = get_enabled_sonarr_connection_config(database_session, user_id)
    payload = _arr_request(
        _required_str(runtime_config.config.get("url"), "Sonarr URL is missing"),
        runtime_config.api_key,
        "/system/status",
        expect_list=False,
    )
    return TestConnectionResponse(
        ok=True,
        name=str(payload.get("appName") or "Sonarr") if isinstance(payload, dict) else "Sonarr",
        version=str(payload.get("version")) if isinstance(payload, dict) else None,
    )


def _get_existing_settings(
    database_session: Session,
    user_id: UUID,
    source: str,
) -> UserIntegrationSettings | None:
    """Return an existing settings row without creating a fallback."""
    return (
        database_session.query(UserIntegrationSettings)
        .filter(
            UserIntegrationSettings.user_id == user_id,
            UserIntegrationSettings.source == source,
        )
        .first()
    )


def _get_or_create_settings(
    database_session: Session,
    user_id: UUID,
    source: str,
) -> UserIntegrationSettings:
    """Return a disabled empty settings row for the user and source."""
    row = _get_existing_settings(database_session, user_id, source)
    if row is not None:
        return row
    row = UserIntegrationSettings(
        user_id=user_id,
        source=source,
        enabled=False,
        config={},
        encrypted_secrets={},
    )
    database_session.add(row)
    database_session.flush()
    return row


def _apply_patch(
    row: UserIntegrationSettings,
    updates: dict[str, Any],
    config_keys: set[str],
) -> None:
    """Apply a partial settings update to config and encrypted secrets."""
    if "enabled" in updates:
        row.enabled = bool(updates.pop("enabled"))

    encrypted_secrets = dict(row.encrypted_secrets or {})
    for secret_key in (SECRET_API_KEY, SECRET_WEBHOOK_SECRET):
        if secret_key in updates:
            secret_value = updates.pop(secret_key)
            if secret_value:
                encrypted_secrets[secret_key] = IntegrationSecretCipher().encrypt(str(secret_value))

    config = dict(row.config or {})
    for key, value in updates.items():
        if key in config_keys:
            config[key] = value

    row.config = config
    row.encrypted_secrets = encrypted_secrets


def _radarr_response(row: UserIntegrationSettings) -> RadarrSettingsResponse:
    """Build a masked Radarr response."""
    config = row.config or {}
    secrets = row.encrypted_secrets or {}
    return RadarrSettingsResponse(
        enabled=bool(row.enabled),
        configured=_radarr_configured(row),
        url=config.get("url"),
        api_key_set=bool(secrets.get(SECRET_API_KEY)),
        webhook_secret_set=bool(secrets.get(SECRET_WEBHOOK_SECRET)),
        root_folder_path=config.get("root_folder_path"),
        quality_profile_id=config.get("quality_profile_id"),
    )


def _sonarr_response(row: UserIntegrationSettings) -> SonarrSettingsResponse:
    """Build a masked Sonarr response."""
    config = row.config or {}
    secrets = row.encrypted_secrets or {}
    return SonarrSettingsResponse(
        enabled=bool(row.enabled),
        configured=_sonarr_configured(row),
        url=config.get("url"),
        api_key_set=bool(secrets.get(SECRET_API_KEY)),
        webhook_secret_set=bool(secrets.get(SECRET_WEBHOOK_SECRET)),
        root_folder_path=config.get("root_folder_path"),
        anime_root_folder_path=config.get("anime_root_folder_path"),
        quality_profile_id=config.get("quality_profile_id"),
        on_air_quality_profile_id=config.get("on_air_quality_profile_id"),
        complete_quality_profile_id=config.get("complete_quality_profile_id"),
        anime_quality_profile_id=config.get("anime_quality_profile_id"),
        language_profile_id=config.get("language_profile_id"),
        anime_language_profile_id=config.get("anime_language_profile_id"),
        series_type=config.get("series_type"),
        anime_series_type=config.get("anime_series_type"),
        monitor_mode=config.get("monitor_mode"),
        on_air_recency_days=config.get("on_air_recency_days"),
        season_folder=config.get("season_folder"),
        anime_tag_label=config.get("anime_tag_label"),
        on_air_tag_label=config.get("on_air_tag_label"),
        complete_tag_label=config.get("complete_tag_label"),
        use_anime_series_type=config.get("use_anime_series_type"),
    )


def _summary(row: UserIntegrationSettings, configured: bool) -> IntegrationSummary:
    """Build a masked integration summary."""
    config = row.config or {}
    secrets = row.encrypted_secrets or {}
    return IntegrationSummary(
        enabled=bool(row.enabled),
        configured=configured,
        url=config.get("url"),
        api_key_set=bool(secrets.get(SECRET_API_KEY)),
        webhook_secret_set=bool(secrets.get(SECRET_WEBHOOK_SECRET)),
    )


def _radarr_configured(row: UserIntegrationSettings) -> bool:
    """Return whether Radarr has the minimum required config."""
    config = row.config or {}
    secrets = row.encrypted_secrets or {}
    return bool(
        config.get("url")
        and config.get("root_folder_path")
        and config.get("quality_profile_id") is not None
        and secrets.get(SECRET_API_KEY)
    )


def _connection_configured(row: UserIntegrationSettings) -> bool:
    """Return whether integration has the connection fields needed for explicit calls."""
    config = row.config or {}
    secrets = row.encrypted_secrets or {}
    return bool(config.get("url") and secrets.get(SECRET_API_KEY))


def _sonarr_configured(row: UserIntegrationSettings) -> bool:
    """Return whether Sonarr has the minimum required config."""
    config = row.config or {}
    secrets = row.encrypted_secrets or {}
    return bool(
        config.get("url")
        and config.get("root_folder_path")
        and config.get("quality_profile_id") is not None
        and secrets.get(SECRET_API_KEY)
    )


def _runtime_config(row: UserIntegrationSettings) -> IntegrationRuntimeConfig:
    """Build decrypted runtime config from one settings row."""
    secrets = row.encrypted_secrets or {}
    cipher = IntegrationSecretCipher()
    api_key = cipher.decrypt(secrets.get(SECRET_API_KEY))
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{row.source} API key is not configured",
        )
    return IntegrationRuntimeConfig(
        source=str(row.source),
        config=dict(row.config or {}),
        api_key=api_key,
        webhook_secret=cipher.decrypt(secrets.get(SECRET_WEBHOOK_SECRET)),
    )


def _arr_request(
    url: str,
    api_key: str,
    path: str,
    expect_list: bool = True,
) -> Any:
    """Call one Radarr/Sonarr API endpoint and validate the coarse shape."""
    try:
        response = httpx.get(
            f"{url.rstrip('/')}/api/v3{path}",
            headers={"X-Api-Key": api_key},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to contact integration server",
        ) from error
    if expect_list and not isinstance(payload, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected integration server response",
        )
    return payload


def _safe_arr_request(url: str, api_key: str, path: str) -> list[dict[str, Any]]:
    """Call an optional endpoint and return an empty list when unavailable."""
    try:
        payload = _arr_request(url, api_key, path)
    except HTTPException:
        return []
    return payload if isinstance(payload, list) else []


def _required_str(value: Any, error_detail: str) -> str:
    """Return a non-empty string or raise a 409 config error."""
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_detail)
    return text
