"""Sonarr integration service for TV series ownership and requests."""

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.settings import settings

SONARR_SERIES_TYPE = "standard"
SONARR_ANIME_SERIES_TYPE = "anime"
SONARR_MONITOR_MODE = "all"
SONARR_SEASON_FOLDER = True
SONARR_USE_ANIME_SERIES_TYPE = True


class SonarrService:
    """Client wrapper for Sonarr TV library operations."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        root_folder_path: str | None = None,
        anime_root_folder_path: str | None = None,
        quality_profile_id: int | None = None,
        on_air_quality_profile_id: int | None = None,
        complete_quality_profile_id: int | None = None,
        anime_quality_profile_id: int | None = None,
        language_profile_id: int | None = None,
        anime_language_profile_id: int | None = None,
        series_type: str | None = None,
        anime_series_type: str | None = None,
        monitor_mode: str | None = None,
        season_folder: bool | None = None,
        use_anime_series_type: bool | None = None,
    ):
        self.url: str = (url or settings.SONARR_URL).rstrip("/")
        self.api_key: str = api_key or settings.SONARR_API_KEY
        self.root_folder_path: str = root_folder_path or settings.SONARR_ROOT_FOLDER_PATH
        self.anime_root_folder_path: str = anime_root_folder_path or settings.SONARR_ANIME_ROOT_FOLDER_PATH
        self.quality_profile_id: int = quality_profile_id or settings.SONARR_QUALITY_PROFILE_ID
        self.on_air_quality_profile_id: int | None = on_air_quality_profile_id or settings.SONARR_ON_AIR_QUALITY_PROFILE_ID
        self.complete_quality_profile_id: int | None = complete_quality_profile_id or settings.SONARR_COMPLETE_QUALITY_PROFILE_ID
        self.anime_quality_profile_id: int | None = anime_quality_profile_id or settings.SONARR_ANIME_QUALITY_PROFILE_ID
        self.language_profile_id: int | None = language_profile_id or settings.SONARR_LANGUAGE_PROFILE_ID
        self.anime_language_profile_id: int | None = anime_language_profile_id or settings.SONARR_ANIME_LANGUAGE_PROFILE_ID
        self.series_type: str = series_type or SONARR_SERIES_TYPE
        self.anime_series_type: str = anime_series_type or SONARR_ANIME_SERIES_TYPE
        self.monitor_mode: str = monitor_mode or SONARR_MONITOR_MODE
        self.season_folder: bool = SONARR_SEASON_FOLDER if season_folder is None else season_folder
        self.use_anime_series_type: bool = (
            SONARR_USE_ANIME_SERIES_TYPE
            if use_anime_series_type is None
            else use_anime_series_type
        )

    def get_series(self) -> list[dict[str, Any]]:
        """Fetch series currently known by Sonarr."""
        payload = self._request("GET", "/series")
        if not isinstance(payload, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Sonarr series library response",
            )
        return payload

    def get_series_by_tvdb_id(self, tvdb_id: int) -> dict[str, Any] | None:
        """Return an existing Sonarr series by TVDB ID if present."""
        for series in self.get_series():
            if _safe_int(series.get("tvdbId")) == tvdb_id:
                return series
        return None

    def lookup_series_by_tvdb_id(self, tvdb_id: int) -> dict[str, Any]:
        """Lookup a series in Sonarr by deterministic TVDB ID."""
        results = self._request("GET", "/series/lookup", params={"term": f"tvdb:{tvdb_id}"})
        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Series was not found by Sonarr",
            )
        if not isinstance(results, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Sonarr lookup response",
            )
        return results[0]

    def add_series_and_search(
        self,
        tvdb_id: int,
        tmdb_id: int,
        season_number: int | None = None,
        is_anime: bool = False,
        use_on_air_profile: bool = False,
        tag_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Find or add a Sonarr series and trigger series/season search."""
        tag_ids = self._resolve_tag_ids(tag_labels or [])
        existing_series = self.get_series_by_tvdb_id(tvdb_id)
        if existing_series:
            existing_series = self._ensure_existing_series_config(
                existing_series,
                is_anime,
                use_on_air_profile,
                tag_ids,
                season_number,
            )
            sonarr_series_id = _safe_int(existing_series.get("id"))
            if sonarr_series_id:
                commands = (
                    [self.search_season(sonarr_series_id, season_number)]
                    if season_number is not None
                    else self.search_missing_aired_seasons(sonarr_series_id, existing_series)
                )
                command_ids = [self.extract_command_id(command) for command in commands]
                command_ids = [command_id for command_id in command_ids if command_id is not None]
                existing_series["_scenario_search_command_ids"] = command_ids
                existing_series["_scenario_search_command_id"] = command_ids[0] if command_ids else None
            return existing_series

        added_series = self.add_series(
            tvdb_id=tvdb_id,
            tmdb_id=tmdb_id,
            is_anime=is_anime,
            use_on_air_profile=use_on_air_profile,
            season_number=season_number,
            tag_labels=tag_labels,
        )
        sonarr_series_id = _safe_int(added_series.get("id"))
        if sonarr_series_id:
            commands = (
                [self.search_season(sonarr_series_id, season_number)]
                if season_number is not None
                else self.search_missing_aired_seasons(sonarr_series_id, added_series)
            )
            command_ids = [self.extract_command_id(command) for command in commands]
            command_ids = [command_id for command_id in command_ids if command_id is not None]
            added_series["_scenario_search_command_ids"] = command_ids
            added_series["_scenario_search_command_id"] = command_ids[0] if command_ids else None
        return added_series

    def add_series(
        self,
        tvdb_id: int,
        tmdb_id: int,
        is_anime: bool = False,
        use_on_air_profile: bool = False,
        season_number: int | None = None,
        tag_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a TV series to Sonarr without triggering search."""
        series = self.lookup_series_by_tvdb_id(tvdb_id)
        tag_ids = self._resolve_tag_ids(tag_labels or [])
        config = self._profile_config(is_anime, use_on_air_profile)
        monitor_mode = "missing" if season_number is not None else self.monitor_mode
        self._apply_new_series_season_monitoring(series, season_number)
        payload = {
            **series,
            "tvdbId": tvdb_id,
            "rootFolderPath": config["rootFolderPath"],
            "qualityProfileId": config["qualityProfileId"],
            "monitored": True,
            "monitor": monitor_mode,
            "seasonFolder": self.season_folder,
            "addOptions": {
                "monitor": monitor_mode,
                "searchForMissingEpisodes": False,
                "searchForCutoffUnmetEpisodes": False,
            },
            "tags": tag_ids,
            "seriesType": config["seriesType"],
        }

        language_profile_id = config.get("languageProfileId")
        if language_profile_id is not None:
            payload["languageProfileId"] = language_profile_id

        added_series = self._request("POST", "/series", json=payload)
        if not isinstance(added_series, dict):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Sonarr add series response",
            )
        return added_series

    def search_series(self, sonarr_series_id: int) -> dict[str, Any] | None:
        """Queue an automatic Sonarr search for all monitored episodes."""
        return self._command("SeriesSearch", seriesId=sonarr_series_id)

    def search_missing_aired_seasons(
        self,
        sonarr_series_id: int,
        series: dict[str, Any] | None = None,
    ) -> list[dict[str, Any] | None]:
        """Queue season searches only for seasons with missing aired episodes.

        Whole-series searches can grab packs that include already imported seasons.
        Searching the missing seasons individually keeps Scenario thin while letting
        Sonarr decide the best release for each remaining season.
        """
        episodes = self.get_episodes(sonarr_series_id)
        missing_season_numbers = sorted(
            {
                season_number
                for episode in episodes
                if (season_number := _safe_int(episode.get("seasonNumber"))) is not None
                and season_number > 0
                and episode.get("hasFile") is not True
                and _sonarr_episode_has_aired(episode)
            },
        )
        if not missing_season_numbers:
            return []

        if series is not None:
            self._ensure_seasons_monitored(series, missing_season_numbers)

        return [
            self.search_season(sonarr_series_id, season_number)
            for season_number in missing_season_numbers
        ]

    def search_season(self, sonarr_series_id: int, season_number: int) -> dict[str, Any] | None:
        """Queue an automatic Sonarr search for one season."""
        return self._command(
            "SeasonSearch",
            seriesId=sonarr_series_id,
            seasonNumber=season_number,
        )

    def get_episodes(self, sonarr_series_id: int) -> list[dict[str, Any]]:
        """Fetch episodes for a Sonarr series."""
        payload = self._request("GET", "/episode", params={"seriesId": sonarr_series_id})
        if not isinstance(payload, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Sonarr episode response",
            )
        return payload

    def get_queue(self) -> list[dict[str, Any]]:
        """Return current Sonarr queue records."""
        payload = self._request(
            "GET",
            "/queue",
            params={
                "page": 1,
                "pageSize": 100,
                "includeUnknownSeriesItems": "true",
                "includeSeries": "true",
                "includeEpisode": "true",
            },
        )
        records = payload.get("records", []) if isinstance(payload, dict) else []
        if not isinstance(records, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Sonarr queue response",
            )
        return records

    def get_command(self, command_id: int) -> dict[str, Any] | None:
        """Fetch a Sonarr command by ID."""
        try:
            payload = self._request("GET", f"/command/{command_id}")
        except HTTPException as error:
            if error.status_code == status.HTTP_404_NOT_FOUND:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    def get_history(self, page_size: int = 100) -> list[dict[str, Any]]:
        """Fetch recent Sonarr history records."""
        payload = self._request(
            "GET",
            "/history",
            params={"page": 1, "pageSize": page_size, "sortKey": "date", "sortDir": "descending"},
        )
        records = payload.get("records", []) if isinstance(payload, dict) else []
        return records if isinstance(records, list) else []

    def get_history_for_series(
        self,
        sonarr_series_id: int,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch recent Sonarr history records for one series."""
        payload = self._request(
            "GET",
            "/history",
            params={
                "page": 1,
                "pageSize": page_size,
                "seriesId": sonarr_series_id,
                "sortKey": "date",
                "sortDir": "descending",
            },
        )
        records = payload.get("records", []) if isinstance(payload, dict) else []
        return records if isinstance(records, list) else []

    def delete_queue_item(self, queue_item_id: int) -> None:
        """Remove an active Sonarr queue item."""
        self._request("DELETE", f"/queue/{queue_item_id}", params={"removeFromClient": "true"})

    def delete_series_if_unavailable(self, sonarr_series_id: int) -> None:
        """Delete a Sonarr series only when it has no imported episode files."""
        episodes = self.get_episodes(sonarr_series_id)
        if any(episode.get("hasFile") is True for episode in episodes):
            return
        self._request("DELETE", f"/series/{sonarr_series_id}", params={"deleteFiles": "false"})

    @staticmethod
    def extract_command_id(command: dict[str, Any] | None) -> int | None:
        """Extract a Sonarr command ID from a command response."""
        if not command:
            return None
        return _safe_int(command.get("id"))

    def _command(self, name: str, **kwargs: Any) -> dict[str, Any] | None:
        """Execute a Sonarr command."""
        payload = self._request("POST", "/command", json={"name": name, **kwargs})
        return payload if isinstance(payload, dict) else None

    def _ensure_existing_series_config(
        self,
        series: dict[str, Any],
        is_anime: bool,
        use_on_air_profile: bool,
        tag_ids: list[int],
        season_number: int | None = None,
    ) -> dict[str, Any]:
        """Ensure an existing series uses Scenario's Sonarr profile config."""
        config = self._profile_config(is_anime, use_on_air_profile)
        changed = False

        if _safe_int(series.get("qualityProfileId")) != config["qualityProfileId"]:
            series["qualityProfileId"] = config["qualityProfileId"]
            changed = True

        language_profile_id = config.get("languageProfileId")
        if language_profile_id is not None and _safe_int(series.get("languageProfileId")) != language_profile_id:
            series["languageProfileId"] = language_profile_id
            changed = True

        if str(series.get("seriesType") or "") != config["seriesType"]:
            series["seriesType"] = config["seriesType"]
            changed = True

        if self._can_update_root_folder(series) and not _same_path(
            series.get("rootFolderPath"),
            config["rootFolderPath"],
        ):
            series["rootFolderPath"] = config["rootFolderPath"]
            changed = True

        current_tag_ids = set(series.get("tags") or [])
        missing_tag_ids = [tag_id for tag_id in tag_ids if tag_id not in current_tag_ids]
        if missing_tag_ids:
            series["tags"] = sorted(current_tag_ids.union(missing_tag_ids))
            changed = True

        if series.get("monitored") is not True:
            series["monitored"] = True
            changed = True

        if season_number is not None:
            for season in series.get("seasons") or []:
                if _safe_int(season.get("seasonNumber")) == season_number and season.get("monitored") is not True:
                    season["monitored"] = True
                    changed = True

        if changed:
            series_id = _safe_int(series.get("id"))
            if series_id is not None:
                updated_series = self._request("PUT", f"/series/{series_id}", json=series)
                return updated_series if isinstance(updated_series, dict) else series

        return series

    def _ensure_seasons_monitored(
        self,
        series: dict[str, Any],
        season_numbers: list[int],
    ) -> dict[str, Any]:
        """Ensure seasons being searched are monitored in Sonarr."""
        missing_season_numbers = set(season_numbers)
        changed = False
        if series.get("monitored") is not True:
            series["monitored"] = True
            changed = True

        for season in series.get("seasons") or []:
            season_number = _safe_int(season.get("seasonNumber"))
            if season_number in missing_season_numbers and season.get("monitored") is not True:
                season["monitored"] = True
                changed = True

        if not changed:
            return series

        series_id = _safe_int(series.get("id"))
        if series_id is None:
            return series
        updated_series = self._request("PUT", f"/series/{series_id}", json=series)
        return updated_series if isinstance(updated_series, dict) else series

    @staticmethod
    def _apply_new_series_season_monitoring(
        series: dict[str, Any],
        season_number: int | None,
    ) -> None:
        """Set initial season monitoring for new Sonarr series payloads."""
        for season in series.get("seasons") or []:
            current_season_number = _safe_int(season.get("seasonNumber"))
            if current_season_number == 0:
                season["monitored"] = False
            elif season_number is not None:
                season["monitored"] = current_season_number == season_number

    @staticmethod
    def _can_update_root_folder(series: dict[str, Any]) -> bool:
        """Return whether a series root folder can be safely corrected."""
        episode_file_count = 0
        for season in series.get("seasons") or []:
            statistics = season.get("statistics") or {}
            episode_file_count += _safe_int(statistics.get("episodeFileCount")) or 0
        return episode_file_count == 0

    def _resolve_tag_ids(self, tag_labels: list[str]) -> list[int]:
        """Resolve Sonarr tag labels to tag IDs, creating missing tags."""
        tag_ids: list[int] = []
        for label in tag_labels:
            normalized_label = str(label or "").strip()
            if not normalized_label:
                continue
            tag_id = self._get_or_create_tag_id(normalized_label)
            if tag_id is not None:
                tag_ids.append(tag_id)
        return tag_ids

    def _get_or_create_tag_id(self, label: str) -> int | None:
        """Return a Sonarr tag ID for label, creating it when missing."""
        tags = self._request("GET", "/tag")
        if not isinstance(tags, list):
            return None

        for tag in tags:
            if str(tag.get("label") or "").lower() == label.lower():
                return _safe_int(tag.get("id"))

        created_tag = self._request("POST", "/tag", json={"label": label})
        if not isinstance(created_tag, dict):
            return None
        return _safe_int(created_tag.get("id"))

    def _profile_config(self, is_anime: bool, use_on_air_profile: bool = False) -> dict[str, Any]:
        """Return Sonarr profile config for a normal or anime series."""
        quality_profile_id = self.quality_profile_id
        if not is_anime and use_on_air_profile and self.on_air_quality_profile_id is not None:
            quality_profile_id = self.on_air_quality_profile_id
        if not is_anime and not use_on_air_profile and self.complete_quality_profile_id is not None:
            quality_profile_id = self.complete_quality_profile_id
        if is_anime and self.anime_quality_profile_id is not None:
            quality_profile_id = self.anime_quality_profile_id

        language_profile_id = self.language_profile_id
        if is_anime and self.anime_language_profile_id is not None:
            language_profile_id = self.anime_language_profile_id

        root_folder_path = self.root_folder_path
        if is_anime and self.anime_root_folder_path:
            root_folder_path = self.anime_root_folder_path

        series_type = self.series_type
        if is_anime and self.use_anime_series_type:
            series_type = self.anime_series_type

        return {
            "rootFolderPath": root_folder_path,
            "qualityProfileId": quality_profile_id,
            "languageProfileId": language_profile_id,
            "seriesType": series_type,
        }

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an authenticated Sonarr API request."""
        if not self.url or not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Sonarr integration is not configured",
            )

        try:
            with httpx.Client(timeout=20) as client:
                response = client.request(
                    method,
                    f"{self.url}/api/v3{path}",
                    params=params,
                    json=json,
                    headers={"X-Api-Key": self.api_key},
                )
                response.raise_for_status()
                if response.content:
                    return response.json()
                return None
        except httpx.HTTPStatusError as error:
            if error.response.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Sonarr resource was not found",
                ) from error
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Sonarr request failed",
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to contact Sonarr",
            ) from error


def _safe_int(value: object) -> int | None:
    """Coerce a value to int, returning None for invalid values."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _same_path(first: object, second: object) -> bool:
    """Compare Sonarr paths while ignoring trailing slashes."""
    return str(first or "").rstrip("/") == str(second or "").rstrip("/")


def _sonarr_episode_has_aired(episode: dict[str, Any]) -> bool:
    """Return whether a Sonarr episode has aired."""
    air_date = str(episode.get("airDateUtc") or episode.get("airDate") or "")
    if not air_date:
        return False
    try:
        aired_at = datetime.fromisoformat(air_date.replace("Z", "+00:00"))
    except ValueError:
        return False
    if aired_at.tzinfo is None:
        aired_at = aired_at.replace(tzinfo=timezone.utc)
    return aired_at <= datetime.now(timezone.utc)
