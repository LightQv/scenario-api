"""Schemas for per-user integration settings."""

from typing import Any, Literal

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


class RadarrSettingsPatch(BaseModel):
    """Partial Radarr settings update."""

    enabled: bool | None = None
    url: str | None = None
    api_key: str | None = Field(default=None, min_length=1)
    webhook_secret: str | None = Field(default=None, min_length=1)
    root_folder_path: str | None = None
    quality_profile_id: int | None = None


class SonarrSettingsResponse(BaseModel):
    """Masked Sonarr settings returned to the client."""

    enabled: bool
    configured: bool
    url: str | None = None
    api_key_set: bool = False
    webhook_secret_set: bool = False
    profiles: dict[str, "SonarrProfileConfig"] = Field(default_factory=dict)


class SonarrSettingsPatch(BaseModel):
    """Partial Sonarr settings update."""

    enabled: bool | None = None
    url: str | None = None
    api_key: str | None = Field(default=None, min_length=1)
    webhook_secret: str | None = Field(default=None, min_length=1)
    profiles: dict[str, "SonarrProfileConfig"] | None = None


SonarrProfileType = Literal["tv_on_air", "tv_complete", "anime"]


class SonarrProfileConfig(BaseModel):
    """One Scenario Sonarr profile configuration."""

    root_folder_path: str
    quality_profile_id: int
    language_profile_id: int | None = None


class SonarrProfileUpsert(BaseModel):
    """Create or replace one Scenario Sonarr profile configuration."""

    root_folder_path: str
    quality_profile_id: int
    language_profile_id: int | None = None


class SelectOption(BaseModel):
    """Generic selectable option."""

    label: str
    value: str | int | bool
    meta: dict[str, Any] = Field(default_factory=dict)


class RadarrOptionsResponse(BaseModel):
    """Radarr selectable settings options."""

    quality_profiles: list[SelectOption]
    root_folders: list[SelectOption]


class SonarrOptionsResponse(BaseModel):
    """Sonarr selectable settings options."""

    quality_profiles: list[SelectOption]
    language_profiles: list[SelectOption]
    root_folders: list[SelectOption]


class TestConnectionResponse(BaseModel):
    """Integration connection test result."""

    ok: bool
    name: str | None = None
    version: str | None = None

    model_config = ConfigDict(from_attributes=True)
