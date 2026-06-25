"""Schemas for per-user integration settings."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IntegrationSummary(BaseModel):
    """Short integration settings status for settings index pages."""

    enabled: bool
    configured: bool
    url: str | None = None
    api_key_set: bool = False
    webhook_secret_set: bool = False


class DownloadSettingsOverview(BaseModel):
    """Overview of user download integrations."""

    radarr: IntegrationSummary
    sonarr: IntegrationSummary


class RadarrSettingsResponse(BaseModel):
    """Masked Radarr settings returned to the client."""

    enabled: bool
    configured: bool
    url: str | None = None
    api_key_set: bool = False
    webhook_secret_set: bool = False
    root_folder_path: str | None = None
    quality_profile_id: int | None = None
    minimum_availability: str | None = None


class RadarrSettingsPatch(BaseModel):
    """Partial Radarr settings update."""

    enabled: bool | None = None
    url: str | None = None
    api_key: str | None = Field(default=None, min_length=1)
    webhook_secret: str | None = Field(default=None, min_length=1)
    root_folder_path: str | None = None
    quality_profile_id: int | None = None
    minimum_availability: str | None = None


class SonarrSettingsResponse(BaseModel):
    """Masked Sonarr settings returned to the client."""

    enabled: bool
    configured: bool
    url: str | None = None
    api_key_set: bool = False
    webhook_secret_set: bool = False
    root_folder_path: str | None = None
    anime_root_folder_path: str | None = None
    quality_profile_id: int | None = None
    on_air_quality_profile_id: int | None = None
    complete_quality_profile_id: int | None = None
    anime_quality_profile_id: int | None = None
    language_profile_id: int | None = None
    anime_language_profile_id: int | None = None
    series_type: str | None = None
    anime_series_type: str | None = None
    monitor_mode: str | None = None
    on_air_recency_days: int | None = None
    season_folder: bool | None = None
    anime_tag_label: str | None = None
    on_air_tag_label: str | None = None
    complete_tag_label: str | None = None
    use_anime_series_type: bool | None = None


class SonarrSettingsPatch(BaseModel):
    """Partial Sonarr settings update."""

    enabled: bool | None = None
    url: str | None = None
    api_key: str | None = Field(default=None, min_length=1)
    webhook_secret: str | None = Field(default=None, min_length=1)
    root_folder_path: str | None = None
    anime_root_folder_path: str | None = None
    quality_profile_id: int | None = None
    on_air_quality_profile_id: int | None = None
    complete_quality_profile_id: int | None = None
    anime_quality_profile_id: int | None = None
    language_profile_id: int | None = None
    anime_language_profile_id: int | None = None
    series_type: str | None = None
    anime_series_type: str | None = None
    monitor_mode: str | None = None
    on_air_recency_days: int | None = None
    season_folder: bool | None = None
    anime_tag_label: str | None = None
    on_air_tag_label: str | None = None
    complete_tag_label: str | None = None
    use_anime_series_type: bool | None = None


class SelectOption(BaseModel):
    """Generic selectable option."""

    label: str
    value: str | int | bool
    meta: dict[str, Any] = Field(default_factory=dict)


class RadarrOptionsResponse(BaseModel):
    """Radarr selectable settings options."""

    quality_profiles: list[SelectOption]
    root_folders: list[SelectOption]
    minimum_availability: list[SelectOption]


class SonarrOptionsResponse(BaseModel):
    """Sonarr selectable settings options."""

    quality_profiles: list[SelectOption]
    language_profiles: list[SelectOption]
    root_folders: list[SelectOption]
    tags: list[SelectOption]
    series_types: list[SelectOption]
    monitor_modes: list[SelectOption]


class TestConnectionResponse(BaseModel):
    """Integration connection test result."""

    ok: bool
    name: str | None = None
    version: str | None = None

    model_config = ConfigDict(from_attributes=True)
