"""
Owned media service.

This module reconciles integration data into Scenario's normalized owned media
table and provides cheap DB-backed availability checks for the mobile app.
"""

from datetime import datetime, timedelta
from threading import Lock
from time import perf_counter

from sqlalchemy.orm import Session

from app.core.logger import log
from app.models import IntegrationSyncStatus, OwnedMedia
from app.schemas import (
    OwnedMediaResponse,
    OwnedMediaStatusResponse,
    OwnedMediaSyncResponse,
    OwnedMediaSyncStatusResponse,
)
from app.services.radarr_service import RadarrService

RADARR_SOURCE = "RADARR"
MOVIE_MEDIA_TYPE = "movie"
SYNC_STATUS_IDLE = "idle"
SYNC_STATUS_RUNNING = "running"
SYNC_STATUS_SUCCESS = "success"
SYNC_STATUS_FAILED = "failed"
SYNC_TRIGGER_MANUAL = "manual"
SYNC_TRIGGER_SCHEDULED = "scheduled"
STALE_RUNNING_SYNC_AFTER = timedelta(hours=2)
_radarr_movie_sync_lock = Lock()


class SyncAlreadyRunningError(Exception):
    """
    Raised when a sync is requested while the same source/type is already running.
    """


def sync_radarr_owned_movies(
    database_session: Session,
    trigger: str = SYNC_TRIGGER_MANUAL,
) -> OwnedMediaSyncResponse:
    """
    Sync Radarr-owned movies into the owned media table.

    The sync stores only movies that Radarr reports as having an imported file.
    Current Radarr/movie rows are replaced atomically with the latest Radarr
    snapshot to remove stale ownership rows.

    Args:
        database_session: Database session dependency.
        trigger: Sync trigger source, either ``manual`` or ``scheduled``.

    Returns:
        OwnedMediaSyncResponse: Summary of the sync result.

    Raises:
        SyncAlreadyRunningError: If the same source/media type is already syncing.
        Exception: Any integration or database error raised during sync.
    """
    sync_label = f"{RADARR_SOURCE} {MOVIE_MEDIA_TYPE}"

    if not _radarr_movie_sync_lock.acquire(blocking=False):
        log.info("Owned media sync skipped: {} sync is already running", sync_label)
        raise SyncAlreadyRunningError(f"{sync_label} sync is already running")

    started_at = perf_counter()

    try:
        _mark_sync_running(database_session, RADARR_SOURCE, MOVIE_MEDIA_TYPE, trigger)
        log.info("Owned media sync started: {} trigger={}", sync_label, trigger)
        synced_at = datetime.utcnow()
        tmdb_ids = RadarrService().get_owned_movie_tmdb_ids()

        (
            database_session.query(OwnedMedia)
            .filter(
                OwnedMedia.source == RADARR_SOURCE,
                OwnedMedia.media_type == MOVIE_MEDIA_TYPE,
            )
            .delete(synchronize_session=False)
        )

        database_session.add_all(
            OwnedMedia(
                tmdb_id=tmdb_id,
                media_type=MOVIE_MEDIA_TYPE,
                source=RADARR_SOURCE,
                last_synced_at=synced_at,
            )
            for tmdb_id in tmdb_ids
        )
        _mark_sync_finished(
            database_session,
            RADARR_SOURCE,
            MOVIE_MEDIA_TYPE,
            SYNC_STATUS_SUCCESS,
            owned_count=len(tmdb_ids),
        )
        database_session.commit()

        duration_seconds = perf_counter() - started_at
        log.info(
            "Owned media sync completed: {} owned_count={} trigger={} duration={:.2f}s",
            sync_label,
            len(tmdb_ids),
            trigger,
            duration_seconds,
        )

        return OwnedMediaSyncResponse(
            source=RADARR_SOURCE,
            media_type=MOVIE_MEDIA_TYPE,
            owned_count=len(tmdb_ids),
            synced_at=synced_at,
        )
    except SyncAlreadyRunningError as error:
        database_session.rollback()
        log.info("Owned media sync skipped: {}", error)
        raise
    except Exception as error:
        database_session.rollback()
        _mark_sync_failed(database_session, RADARR_SOURCE, MOVIE_MEDIA_TYPE, str(error))
        duration_seconds = perf_counter() - started_at
        log.exception(
            "Owned media sync failed: {} trigger={} duration={:.2f}s error={}",
            sync_label,
            trigger,
            duration_seconds,
            error,
        )
        raise
    finally:
        _radarr_movie_sync_lock.release()


def get_radarr_owned_movies_sync_status(
    database_session: Session,
) -> OwnedMediaSyncStatusResponse:
    """
    Return Radarr movie sync status for profile/admin UI state.

    Args:
        database_session: Database session dependency.

    Returns:
        OwnedMediaSyncStatusResponse: Current or latest sync status.
    """
    sync_status = _get_or_create_sync_status(
        database_session,
        RADARR_SOURCE,
        MOVIE_MEDIA_TYPE,
    )
    database_session.commit()

    if _is_stale_running_sync(sync_status):
        sync_status.status = SYNC_STATUS_FAILED
        sync_status.finished_at = datetime.utcnow()
        sync_status.error_message = "Sync was interrupted before completion."
        database_session.commit()

    return OwnedMediaSyncStatusResponse.model_validate(sync_status)


def _get_or_create_sync_status(
    database_session: Session,
    source: str,
    media_type: str,
) -> IntegrationSyncStatus:
    """
    Return the sync status row for a source/type pair, creating it if needed.

    Args:
        database_session: Database session dependency.
        source: Integration source.
        media_type: Synced media type.

    Returns:
        IntegrationSyncStatus: Existing or newly-created status row.
    """
    sync_status = (
        database_session.query(IntegrationSyncStatus)
        .filter(
            IntegrationSyncStatus.source == source,
            IntegrationSyncStatus.media_type == media_type,
        )
        .first()
    )

    if sync_status:
        return sync_status

    sync_status = IntegrationSyncStatus(
        source=source,
        media_type=media_type,
        status=SYNC_STATUS_IDLE,
    )
    database_session.add(sync_status)
    database_session.flush()
    return sync_status


def _mark_sync_running(
    database_session: Session,
    source: str,
    media_type: str,
    trigger: str,
) -> None:
    """
    Mark a sync as running, rejecting non-stale overlapping syncs.

    Args:
        database_session: Database session dependency.
        source: Integration source.
        media_type: Synced media type.
        trigger: Sync trigger source.

    Raises:
        SyncAlreadyRunningError: If a fresh sync is already running.
    """
    sync_status = _get_or_create_sync_status(database_session, source, media_type)

    if sync_status.status == SYNC_STATUS_RUNNING and not _is_stale_running_sync(
        sync_status
    ):
        raise SyncAlreadyRunningError(f"{source} {media_type} sync is already running")

    sync_status.status = SYNC_STATUS_RUNNING
    sync_status.trigger = trigger
    sync_status.started_at = datetime.utcnow()
    sync_status.finished_at = None
    sync_status.error_message = None
    database_session.commit()


def _mark_sync_finished(
    database_session: Session,
    source: str,
    media_type: str,
    sync_status_value: str,
    owned_count: int | None = None,
    error_message: str | None = None,
) -> None:
    """
    Mark a sync as finished without committing the current transaction.

    Args:
        database_session: Database session dependency.
        source: Integration source.
        media_type: Synced media type.
        sync_status_value: Finished status value.
        owned_count: Number of stored owned media rows.
        error_message: Failure message, if any.
    """
    sync_status = _get_or_create_sync_status(database_session, source, media_type)
    sync_status.status = sync_status_value
    sync_status.finished_at = datetime.utcnow()
    sync_status.owned_count = owned_count
    sync_status.error_message = error_message[:500] if error_message else None


def _mark_sync_failed(
    database_session: Session,
    source: str,
    media_type: str,
    error_message: str,
) -> None:
    """
    Persist a failed sync status after rolling back sync data changes.

    Args:
        database_session: Database session dependency.
        source: Integration source.
        media_type: Synced media type.
        error_message: Failure message.
    """
    _mark_sync_finished(
        database_session,
        source,
        media_type,
        SYNC_STATUS_FAILED,
        error_message=error_message,
    )
    database_session.commit()


def _is_stale_running_sync(sync_status: IntegrationSyncStatus) -> bool:
    """
    Return whether a running sync was likely interrupted by process shutdown.

    Args:
        sync_status: Sync status row to inspect.

    Returns:
        bool: True when the running state is older than the stale threshold.
    """
    if sync_status.status != SYNC_STATUS_RUNNING or not sync_status.started_at:
        return False

    return datetime.utcnow() - sync_status.started_at > STALE_RUNNING_SYNC_AFTER


def get_owned_media(database_session: Session) -> list[OwnedMediaResponse]:
    """
    Return all owned media rows from Scenario's database.

    Args:
        database_session: Database session dependency.

    Returns:
        list[OwnedMediaResponse]: Owned media rows.
    """
    owned_media = database_session.query(OwnedMedia).all()
    return [OwnedMediaResponse.model_validate(item) for item in owned_media]


def get_owned_media_status(
    tmdb_id: int,
    media_type: str,
    database_session: Session,
) -> OwnedMediaStatusResponse:
    """
    Check if a media is owned using Scenario's local database only.

    Args:
        tmdb_id: TMDB media identifier.
        media_type: Media type to check.
        database_session: Database session dependency.

    Returns:
        OwnedMediaStatusResponse: Boolean ownership result.
    """
    owned = (
        database_session.query(OwnedMedia.id)
        .filter(
            OwnedMedia.tmdb_id == tmdb_id,
            OwnedMedia.media_type == media_type,
        )
        .first()
        is not None
    )

    return OwnedMediaStatusResponse(
        tmdb_id=tmdb_id,
        media_type=media_type,
        owned=owned,
    )
