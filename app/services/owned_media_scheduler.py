"""
Owned media background scheduler.

This module runs per-user Radarr/Sonarr owned media syncs at fixed local clock
hours so syncs do not drift based on container startup time.
"""

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.logger import log
from app.core.settings import settings
from app.database.session import SessionLocal
from app.services.owned_media_service import (
    RADARR_SOURCE,
    SYNC_TRIGGER_SCHEDULED,
    SONARR_SOURCE,
    SyncAlreadyRunningError,
    sync_radarr_owned_movies,
    sync_sonarr_owned_tv,
)
from app.services.radarr_service import RadarrService
from app.services.sonarr_service import SonarrService
from app.services.user_integration_settings_service import (
    IntegrationRuntimeConfig,
    get_enabled_runtime_configs,
)


class OwnedMediaScheduler:
    """
    Runs owned media syncs at configured wall-clock hours.

    The scheduler owns its database session per sync run and executes the
    blocking Radarr/database work in a thread to avoid blocking FastAPI's event
    loop.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """
        Start the background scheduler task if enabled.
        """
        if not settings.OWNED_MEDIA_AUTO_SYNC_ENABLED:
            log.info("Owned media auto-sync scheduler is disabled")
            return

        if self._task and not self._task.done():
            return

        self._task = asyncio.create_task(
            self._run(),
            name="owned-media-sync-scheduler",
        )

    async def stop(self) -> None:
        """
        Stop the background scheduler task cleanly.
        """
        if not self._task:
            return

        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        """
        Run the scheduler loop until cancelled.
        """
        timezone = self._get_timezone()
        sync_hours = self._get_sync_hours()

        log.info(
            "Owned media auto-sync scheduled at hours {} in timezone {}",
            sync_hours,
            timezone.key,
        )

        while True:
            now = datetime.now(timezone)
            next_run = self._get_next_run(now, sync_hours)
            delay_seconds = max((next_run - now).total_seconds(), 0)

            log.info("Next owned media auto-sync scheduled for {}", next_run.isoformat())
            await asyncio.sleep(delay_seconds)

            await asyncio.to_thread(self._sync_once)

    def _sync_once(self) -> None:
        """
        Execute one per-user integration sync batch with an isolated database session.
        """
        database_session = SessionLocal()
        try:
            for user_id, runtime_config in get_enabled_runtime_configs(database_session, RADARR_SOURCE):
                try:
                    sync_radarr_owned_movies(
                        database_session,
                        user_id,
                        trigger=SYNC_TRIGGER_SCHEDULED,
                        radarr_service=_radarr_service_from_runtime_config(runtime_config),
                    )
                except SyncAlreadyRunningError:
                    database_session.rollback()
                except Exception as error:  # pylint: disable=broad-exception-caught
                    database_session.rollback()
                    log.exception(
                        "Scheduled Radarr owned media sync failed: user_id={} error={}",
                        user_id,
                        error,
                    )

            for user_id, runtime_config in get_enabled_runtime_configs(database_session, SONARR_SOURCE):
                try:
                    sync_sonarr_owned_tv(
                        database_session,
                        user_id,
                        trigger=SYNC_TRIGGER_SCHEDULED,
                        sonarr_service=_sonarr_service_from_runtime_config(runtime_config),
                    )
                except SyncAlreadyRunningError:
                    database_session.rollback()
                except Exception as error:  # pylint: disable=broad-exception-caught
                    database_session.rollback()
                    log.exception(
                        "Scheduled Sonarr owned media sync failed: user_id={} error={}",
                        user_id,
                        error,
                    )
        except SyncAlreadyRunningError:
            database_session.rollback()
        except Exception:  # pylint: disable=broad-exception-caught
            database_session.rollback()
        finally:
            database_session.close()

    @staticmethod
    def _get_timezone() -> ZoneInfo:
        """
        Return configured scheduler timezone, falling back to UTC if invalid.

        Returns:
            ZoneInfo: Timezone used for fixed-hour scheduling.
        """
        try:
            return ZoneInfo(settings.OWNED_MEDIA_SYNC_TIMEZONE)
        except ZoneInfoNotFoundError:
            log.warning(
                "Invalid owned media sync timezone '{}'; falling back to UTC",
                settings.OWNED_MEDIA_SYNC_TIMEZONE,
            )
            return ZoneInfo("UTC")

    @staticmethod
    def _get_sync_hours() -> list[int]:
        """
        Return configured scheduler hours sorted and deduplicated.

        Returns:
            list[int]: Valid hours in 24-hour clock format.
        """
        sync_hours = sorted(
            {hour for hour in settings.OWNED_MEDIA_SYNC_HOURS if 0 <= hour <= 23}
        )

        if sync_hours:
            return sync_hours

        log.warning(
            "No valid owned media sync hours configured; falling back to [0, 6, 12, 18]"
        )
        return [0, 6, 12, 18]

    @staticmethod
    def _get_next_run(now: datetime, sync_hours: list[int]) -> datetime:
        """
        Calculate the next fixed-hour sync datetime.

        Args:
            now: Current timezone-aware datetime.
            sync_hours: Valid 24-hour clock hours to run syncs.

        Returns:
            datetime: Next scheduled sync datetime in the same timezone as now.
        """
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        for sync_hour in sync_hours:
            candidate = today_start.replace(hour=sync_hour)
            if candidate > now:
                return candidate

        return today_start + timedelta(days=1, hours=sync_hours[0])


def _radarr_service_from_runtime_config(runtime_config: IntegrationRuntimeConfig) -> RadarrService:
    """Build a Radarr service from decrypted per-user settings."""
    config = runtime_config.config
    return RadarrService(
        url=config.get("url"),
        api_key=runtime_config.api_key,
        root_folder_path=config.get("root_folder_path"),
        quality_profile_id=config.get("quality_profile_id"),
    )


def _sonarr_service_from_runtime_config(runtime_config: IntegrationRuntimeConfig) -> SonarrService:
    """Build a Sonarr service from decrypted per-user settings."""
    config = runtime_config.config
    profiles = config.get("profiles") if isinstance(config.get("profiles"), dict) else {}
    tv_on_air_profile = profiles.get("tv_on_air") or {}
    tv_complete_profile = profiles.get("tv_complete") or {}
    anime_profile = profiles.get("anime") or {}
    return SonarrService(
        url=config.get("url"),
        api_key=runtime_config.api_key,
        root_folder_path=tv_on_air_profile.get("root_folder_path") or tv_complete_profile.get("root_folder_path"),
        anime_root_folder_path=anime_profile.get("root_folder_path"),
        quality_profile_id=tv_on_air_profile.get("quality_profile_id") or tv_complete_profile.get("quality_profile_id"),
        on_air_quality_profile_id=tv_on_air_profile.get("quality_profile_id"),
        complete_quality_profile_id=tv_complete_profile.get("quality_profile_id"),
        anime_quality_profile_id=anime_profile.get("quality_profile_id"),
        language_profile_id=tv_on_air_profile.get("language_profile_id") or tv_complete_profile.get("language_profile_id"),
        anime_language_profile_id=anime_profile.get("language_profile_id"),
    )


owned_media_scheduler = OwnedMediaScheduler()
