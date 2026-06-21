"""
Owned media service.

This module reconciles integration data into Scenario's normalized owned media
table and provides cheap DB-backed availability checks for the mobile app.
"""

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    RadarrWebhookPayload,
    RadarrWebhookResponse,
)
from app.services.radarr_service import RadarrService
from app.services.tmdb_service import TmdbMovieMetadata, TmdbService
from app.services.download_request_service import mark_radarr_movie_requests_available
from app.services.download_request_service import mark_radarr_movie_request_grabbed

RADARR_SOURCE = "RADARR"
MOVIE_MEDIA_TYPE = "movie"
SYNC_STATUS_IDLE = "idle"
SYNC_STATUS_RUNNING = "running"
SYNC_STATUS_SUCCESS = "success"
SYNC_STATUS_FAILED = "failed"
SYNC_TRIGGER_MANUAL = "manual"
SYNC_TRIGGER_SCHEDULED = "scheduled"
SYNC_TRIGGER_WEBHOOK = "webhook"
STALE_RUNNING_SYNC_AFTER = timedelta(hours=2)
TMDB_METADATA_WORKERS = 5
_radarr_movie_sync_lock = Lock()
RADARR_IMPORT_EVENTS = {"download", "moviefileimport", "fileimport"}
RADARR_DELETE_EVENTS = {"moviedelete", "moviefiledelete"}
RADARR_GRAB_EVENTS = {"grab", "downloadgrab"}


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

    try:
        return _sync_radarr_owned_movies(
            database_session,
            trigger=trigger,
            mark_running=True,
        )
    finally:
        _radarr_movie_sync_lock.release()


def start_radarr_owned_movies_sync(
    database_session: Session,
    trigger: str = SYNC_TRIGGER_MANUAL,
) -> OwnedMediaSyncStatusResponse:
    """Reserve and mark a Radarr movie sync as running for background work.

    Args:
        database_session: Request database session.
        trigger: Sync trigger source.

    Returns:
        OwnedMediaSyncStatusResponse: Running sync status.

    Raises:
        SyncAlreadyRunningError: If the same source/media type is already syncing.
    """
    sync_label = f"{RADARR_SOURCE} {MOVIE_MEDIA_TYPE}"

    if not _radarr_movie_sync_lock.acquire(blocking=False):
        log.info("Owned media sync skipped: {} sync is already running", sync_label)
        raise SyncAlreadyRunningError(f"{sync_label} sync is already running")

    try:
        _mark_sync_running(database_session, RADARR_SOURCE, MOVIE_MEDIA_TYPE, trigger)
        return get_radarr_owned_movies_sync_status(database_session)
    except Exception:
        _radarr_movie_sync_lock.release()
        raise


def sync_radarr_owned_movies_with_reserved_lock(
    database_session: Session,
    trigger: str = SYNC_TRIGGER_MANUAL,
) -> OwnedMediaSyncResponse:
    """Run a Radarr movie sync after ``start_radarr_owned_movies_sync``.

    Args:
        database_session: Background task database session.
        trigger: Sync trigger source.

    Returns:
        OwnedMediaSyncResponse: Summary of the sync result.
    """
    try:
        return _sync_radarr_owned_movies(
            database_session,
            trigger=trigger,
            mark_running=False,
        )
    finally:
        _radarr_movie_sync_lock.release()


def _sync_radarr_owned_movies(
    database_session: Session,
    trigger: str,
    mark_running: bool,
) -> OwnedMediaSyncResponse:
    """Sync Radarr owned movies with hydrated TMDB metadata."""
    sync_label = f"{RADARR_SOURCE} {MOVIE_MEDIA_TYPE}"

    started_at = perf_counter()

    try:
        if mark_running:
            _mark_sync_running(database_session, RADARR_SOURCE, MOVIE_MEDIA_TYPE, trigger)
        log.info("Owned media sync started: {} trigger={}", sync_label, trigger)
        synced_at = datetime.utcnow()
        tmdb_ids = RadarrService().get_owned_movie_tmdb_ids()
        movie_metadata = _fetch_movie_metadata(tmdb_ids)

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
                tmdb_id=metadata.tmdb_id,
                media_type=metadata.media_type,
                genre_ids=metadata.genre_ids or [0],
                poster_path=metadata.poster_path,
                backdrop_path=metadata.backdrop_path,
                release_date=metadata.release_date,
                release_year=metadata.release_year,
                runtime=metadata.runtime,
                title=metadata.title,
                source=RADARR_SOURCE,
                last_synced_at=synced_at,
                metadata_synced_at=synced_at,
            )
            for metadata in movie_metadata
        )
        _mark_sync_finished(
            database_session,
            RADARR_SOURCE,
            MOVIE_MEDIA_TYPE,
            SYNC_STATUS_SUCCESS,
            owned_count=len(movie_metadata),
        )
        database_session.commit()

        duration_seconds = perf_counter() - started_at
        log.info(
            "Owned media sync completed: {} owned_count={} trigger={} duration={:.2f}s",
            sync_label,
            len(movie_metadata),
            trigger,
            duration_seconds,
        )

        return OwnedMediaSyncResponse(
            source=RADARR_SOURCE,
            media_type=MOVIE_MEDIA_TYPE,
            owned_count=len(movie_metadata),
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


def _fetch_movie_metadata(tmdb_ids: list[int]) -> list[TmdbMovieMetadata]:
    """Fetch TMDB movie metadata with bounded concurrency.

    Args:
        tmdb_ids: TMDB movie identifiers to hydrate.

    Returns:
        list[TmdbMovieMetadata]: Successfully hydrated movie metadata rows.
    """
    tmdb_service = TmdbService()
    movie_metadata: list[TmdbMovieMetadata] = []

    with ThreadPoolExecutor(max_workers=TMDB_METADATA_WORKERS) as executor:
        futures = {
            executor.submit(tmdb_service.get_movie_metadata, tmdb_id): tmdb_id
            for tmdb_id in tmdb_ids
        }

        for future in as_completed(futures):
            tmdb_id = futures[future]
            try:
                movie_metadata.append(future.result())
            except Exception as error:  # pylint: disable=broad-exception-caught
                log.warning(
                    "Owned media metadata skipped: tmdb_id={} error={}",
                    tmdb_id,
                    error,
                )

    return sorted(movie_metadata, key=lambda item: item.title.lower())


def handle_radarr_webhook(
    payload: RadarrWebhookPayload,
    database_session: Session,
) -> RadarrWebhookResponse:
    """Handle Radarr webhook events that affect owned movie availability.

    Args:
        payload: Parsed Radarr webhook payload.
        database_session: Database session dependency.

    Returns:
        RadarrWebhookResponse: Summary of the handled or ignored event.
    """
    event_type = payload.eventType or "unknown"
    normalized_event_type = event_type.lower()

    # Temporary operational log to capture the exact Radarr payload shape in prod.
    log.info("Radarr webhook payload: {}", payload.model_dump(mode="json"))

    if normalized_event_type == "test":
        log.info("Radarr webhook test received")
        return RadarrWebhookResponse(
            status="success",
            event_type=event_type,
            action="test",
        )

    tmdb_id = _extract_radarr_webhook_tmdb_id(payload)
    if not tmdb_id:
        log.info("Radarr webhook ignored: event_type={} missing_tmdb_id", event_type)
        return RadarrWebhookResponse(
            status="ignored",
            event_type=event_type,
            action="missing_tmdb_id",
        )

    try:
        if normalized_event_type in RADARR_IMPORT_EVENTS:
            _upsert_radarr_owned_movie(database_session, tmdb_id)
            updated_requests = mark_radarr_movie_requests_available(
                tmdb_id,
                database_session,
            )
            _mark_webhook_sync_success(database_session)
            database_session.commit()
            log.info(
                "Radarr webhook imported owned movie: tmdb_id={} updated_requests={}",
                tmdb_id,
                updated_requests,
            )
            return RadarrWebhookResponse(
                status="success",
                event_type=event_type,
                action="upserted",
                tmdb_id=tmdb_id,
            )

        if normalized_event_type in RADARR_GRAB_EVENTS:
            updated_requests = mark_radarr_movie_request_grabbed(
                tmdb_id,
                payload.model_dump(mode="json"),
                database_session,
            )
            database_session.commit()
            log.info(
                "Radarr webhook grabbed movie release: tmdb_id={} updated_requests={}",
                tmdb_id,
                updated_requests,
            )
            return RadarrWebhookResponse(
                status="success",
                event_type=event_type,
                action="grabbed",
                tmdb_id=tmdb_id,
            )

        if normalized_event_type in RADARR_DELETE_EVENTS:
            if _is_radarr_upgrade_delete(payload):
                log.info(
                    "Radarr webhook ignored upgrade delete: event_type={} tmdb_id={}",
                    event_type,
                    tmdb_id,
                )
                return RadarrWebhookResponse(
                    status="ignored",
                    event_type=event_type,
                    action="upgrade_delete",
                    tmdb_id=tmdb_id,
                )

            deleted_count = _delete_radarr_owned_movie(database_session, tmdb_id)
            _mark_webhook_sync_success(database_session)
            database_session.commit()
            log.info(
                "Radarr webhook deleted owned movie: tmdb_id={} deleted_count={}",
                tmdb_id,
                deleted_count,
            )
            return RadarrWebhookResponse(
                status="success",
                event_type=event_type,
                action="deleted",
                tmdb_id=tmdb_id,
            )
    except Exception as error:
        database_session.rollback()
        _mark_sync_failed(
            database_session,
            RADARR_SOURCE,
            MOVIE_MEDIA_TYPE,
            str(error),
            trigger=SYNC_TRIGGER_WEBHOOK,
        )
        log.exception(
            "Radarr webhook failed: event_type={} tmdb_id={} error={}",
            event_type,
            tmdb_id,
            error,
        )
        raise

    log.info("Radarr webhook ignored: event_type={} tmdb_id={}", event_type, tmdb_id)
    return RadarrWebhookResponse(
        status="ignored",
        event_type=event_type,
        action="unsupported_event",
        tmdb_id=tmdb_id,
    )


def _extract_radarr_webhook_tmdb_id(payload: RadarrWebhookPayload) -> int | None:
    """Extract a movie TMDB ID from known Radarr webhook payload locations."""
    movie = payload.movie or {}
    data = payload.data or {}
    candidates = [
        movie.get("tmdbId"),
        movie.get("tmdb_id"),
        data.get("tmdbId"),
        data.get("tmdb_id"),
    ]

    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue

    return None


def _upsert_radarr_owned_movie(database_session: Session, tmdb_id: int) -> None:
    """Hydrate and upsert a single Radarr-owned movie row."""
    synced_at = datetime.utcnow()
    metadata = TmdbService().get_movie_metadata(tmdb_id)
    owned_media = (
        database_session.query(OwnedMedia)
        .filter(
            OwnedMedia.tmdb_id == tmdb_id,
            OwnedMedia.media_type == MOVIE_MEDIA_TYPE,
            OwnedMedia.source == RADARR_SOURCE,
        )
        .first()
    )

    if not owned_media:
        owned_media = OwnedMedia(
            tmdb_id=tmdb_id,
            media_type=MOVIE_MEDIA_TYPE,
            source=RADARR_SOURCE,
            last_synced_at=synced_at,
        )
        database_session.add(owned_media)

    owned_media.genre_ids = metadata.genre_ids or [0]
    owned_media.poster_path = metadata.poster_path
    owned_media.backdrop_path = metadata.backdrop_path
    owned_media.release_date = metadata.release_date
    owned_media.release_year = metadata.release_year
    owned_media.runtime = metadata.runtime
    owned_media.title = metadata.title
    owned_media.last_synced_at = synced_at
    owned_media.metadata_synced_at = synced_at


def _delete_radarr_owned_movie(database_session: Session, tmdb_id: int) -> int:
    """Delete one Radarr-owned movie row by TMDB ID."""
    return (
        database_session.query(OwnedMedia)
        .filter(
            OwnedMedia.tmdb_id == tmdb_id,
            OwnedMedia.media_type == MOVIE_MEDIA_TYPE,
            OwnedMedia.source == RADARR_SOURCE,
        )
        .delete(synchronize_session=False)
    )


def _is_radarr_upgrade_delete(payload: RadarrWebhookPayload) -> bool:
    """Return whether a Radarr file-delete webhook is part of an upgrade."""
    if payload.isUpgrade is True:
        return True

    delete_reason = (payload.deleteReason or "").lower()
    return "upgrade" in delete_reason


def _mark_webhook_sync_success(database_session: Session) -> None:
    """Update Radarr movie sync status after a successful webhook action."""
    sync_status = _get_or_create_sync_status(
        database_session,
        RADARR_SOURCE,
        MOVIE_MEDIA_TYPE,
    )
    sync_status.status = SYNC_STATUS_SUCCESS
    sync_status.trigger = SYNC_TRIGGER_WEBHOOK
    sync_status.started_at = datetime.utcnow()
    sync_status.finished_at = sync_status.started_at
    sync_status.owned_count = _count_radarr_owned_movies(database_session)
    sync_status.error_message = None


def _count_radarr_owned_movies(database_session: Session) -> int:
    """Count current Scenario-owned Radarr movies."""
    return (
        database_session.query(OwnedMedia)
        .filter(
            OwnedMedia.source == RADARR_SOURCE,
            OwnedMedia.media_type == MOVIE_MEDIA_TYPE,
        )
        .count()
    )


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
    trigger: str | None = None,
) -> None:
    """
    Persist a failed sync status after rolling back sync data changes.

    Args:
        database_session: Database session dependency.
        source: Integration source.
        media_type: Synced media type.
        error_message: Failure message.
        trigger: Optional sync trigger source.
    """
    _mark_sync_finished(
        database_session,
        source,
        media_type,
        SYNC_STATUS_FAILED,
        error_message=error_message,
    )
    if trigger:
        sync_status = _get_or_create_sync_status(database_session, source, media_type)
        sync_status.trigger = trigger
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
