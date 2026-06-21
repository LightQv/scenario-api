"""Download request service for Radarr movie requests."""

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import DownloadRequest, OwnedMedia, User
from app.schemas import DownloadRequestResponse
from app.services.radarr_service import RadarrService
from app.services.tmdb_service import TmdbMovieMetadata, TmdbService

RADARR_SOURCE = "RADARR"
MOVIE_MEDIA_TYPE = "movie"
ANIMATION_GENRE_ID = 16
ANIME_TAG_LABEL = "anime"

DOWNLOAD_STATUS_REQUESTED = "requested"
DOWNLOAD_STATUS_SENT_TO_RADARR = "sent_to_radarr"
DOWNLOAD_STATUS_SEARCHING = "searching"
DOWNLOAD_STATUS_DOWNLOADING = "downloading"
DOWNLOAD_STATUS_NOT_FOUND = "not_found"
DOWNLOAD_STATUS_FAILED = "failed"
DOWNLOAD_STATUS_AVAILABLE = "available"
DOWNLOAD_STATUS_CANCELLED = "cancelled"

ACTIVE_DOWNLOAD_STATUSES = {
    DOWNLOAD_STATUS_REQUESTED,
    DOWNLOAD_STATUS_SENT_TO_RADARR,
    DOWNLOAD_STATUS_SEARCHING,
    DOWNLOAD_STATUS_DOWNLOADING,
}


def request_radarr_movie_download(
    tmdb_id: int,
    user: User,
    database_session: Session,
) -> DownloadRequestResponse:
    """Create or reuse a Radarr movie request and trigger automatic search."""
    existing_request = get_download_request_for_media(
        tmdb_id,
        MOVIE_MEDIA_TYPE,
        database_session,
    )
    if existing_request and existing_request.status in ACTIVE_DOWNLOAD_STATUSES:
        return DownloadRequestResponse.model_validate(existing_request)

    if _is_owned_movie(tmdb_id, database_session):
        download_request = existing_request or _create_download_request(
            tmdb_id,
            user,
            database_session,
        )
        _mark_request_available(download_request)
        database_session.commit()
        return DownloadRequestResponse.model_validate(download_request)

    metadata = TmdbService().get_movie_metadata(tmdb_id)
    download_request = existing_request or _create_download_request(
        tmdb_id,
        user,
        database_session,
        metadata,
    )
    download_request.status = DOWNLOAD_STATUS_REQUESTED
    download_request.error_message = None
    _clear_queue_fields(download_request)
    database_session.commit()

    try:
        radarr_movie = RadarrService().add_movie_and_search(
            tmdb_id,
            tag_labels=_get_radarr_tag_labels(metadata),
        )
        download_request.radarr_movie_id = _extract_radarr_movie_id(radarr_movie)
        download_request.status = DOWNLOAD_STATUS_SEARCHING
        download_request.error_message = None
        _clear_queue_fields(download_request)
        database_session.commit()
    except HTTPException as error:
        _mark_request_failed(database_session, download_request, str(error.detail))
    except Exception as error:
        _mark_request_failed(database_session, download_request, str(error))

    return DownloadRequestResponse.model_validate(download_request)


def list_download_requests(database_session: Session) -> list[DownloadRequestResponse]:
    """Return all household download requests, newest first."""
    reconcile_download_requests(database_session)
    requests = (
        database_session.query(DownloadRequest)
        .order_by(DownloadRequest.requested_at.desc())
        .all()
    )
    return [DownloadRequestResponse.model_validate(item) for item in requests]


def get_download_request_status(
    tmdb_id: int,
    media_type: str,
    database_session: Session,
) -> DownloadRequestResponse | None:
    """Return the latest download request for a media item, if any."""
    reconcile_download_requests(database_session)
    download_request = get_download_request_for_media(
        tmdb_id,
        media_type,
        database_session,
    )
    if not download_request:
        return None
    return DownloadRequestResponse.model_validate(download_request)


def get_download_request_for_media(
    tmdb_id: int,
    media_type: str,
    database_session: Session,
) -> DownloadRequest | None:
    """Return the latest household request for a media item."""
    return (
        database_session.query(DownloadRequest)
        .filter(
            DownloadRequest.tmdb_id == tmdb_id,
            DownloadRequest.media_type == media_type,
            DownloadRequest.source == RADARR_SOURCE,
        )
        .order_by(DownloadRequest.requested_at.desc())
        .first()
    )


def mark_radarr_movie_requests_available(
    tmdb_id: int,
    database_session: Session,
) -> int:
    """Mark matching Radarr movie requests as available after import webhook."""
    updated_count = (
        database_session.query(DownloadRequest)
        .filter(
            DownloadRequest.tmdb_id == tmdb_id,
            DownloadRequest.media_type == MOVIE_MEDIA_TYPE,
            DownloadRequest.source == RADARR_SOURCE,
            DownloadRequest.status != DOWNLOAD_STATUS_AVAILABLE,
        )
        .update(
            {
                DownloadRequest.status: DOWNLOAD_STATUS_AVAILABLE,
                DownloadRequest.error_message: None,
                DownloadRequest.download_title: None,
                DownloadRequest.download_client: None,
                DownloadRequest.quality: None,
                DownloadRequest.size: None,
                DownloadRequest.size_left: None,
                DownloadRequest.time_left: None,
                DownloadRequest.tracked_download_status: None,
                DownloadRequest.tracked_download_state: None,
            },
            synchronize_session=False,
        )
    )
    return int(updated_count)


def reconcile_download_requests(database_session: Session) -> None:
    """Refresh active download requests from owned media and Radarr queue."""
    active_requests = (
        database_session.query(DownloadRequest)
        .filter(
            DownloadRequest.media_type == MOVIE_MEDIA_TYPE,
            DownloadRequest.source == RADARR_SOURCE,
            DownloadRequest.status.in_(ACTIVE_DOWNLOAD_STATUSES),
        )
        .all()
    )
    if not active_requests:
        return

    pending_requests: list[DownloadRequest] = []
    for download_request in active_requests:
        if _is_owned_movie(download_request.tmdb_id, database_session):
            _mark_request_available(download_request)
        else:
            pending_requests.append(download_request)

    if pending_requests:
        try:
            queue_records = RadarrService().get_queue()
        except HTTPException:
            database_session.commit()
            return
        queue_by_tmdb_id, queue_by_radarr_id = _index_queue_records(queue_records)
        for download_request in pending_requests:
            queue_record = queue_by_tmdb_id.get(download_request.tmdb_id)
            if not queue_record and download_request.radarr_movie_id is not None:
                queue_record = queue_by_radarr_id.get(download_request.radarr_movie_id)
            if queue_record:
                _apply_queue_record(download_request, queue_record)

    database_session.commit()


def _create_download_request(
    tmdb_id: int,
    user: User,
    database_session: Session,
    metadata: TmdbMovieMetadata | None = None,
) -> DownloadRequest:
    """Create a hydrated local download request row."""
    metadata = metadata or TmdbService().get_movie_metadata(tmdb_id)
    requested_at = datetime.utcnow()
    download_request = DownloadRequest(
        user_id=user.id,
        tmdb_id=tmdb_id,
        media_type=MOVIE_MEDIA_TYPE,
        source=RADARR_SOURCE,
        status=DOWNLOAD_STATUS_REQUESTED,
        requested_at=requested_at,
    )
    _apply_metadata(download_request, metadata)
    database_session.add(download_request)
    database_session.flush()
    return download_request


def _get_radarr_tag_labels(metadata: TmdbMovieMetadata) -> list[str]:
    """Return Radarr tags Scenario should apply for a movie request."""
    if _is_anime_movie(metadata):
        return [ANIME_TAG_LABEL]
    return []


def _is_anime_movie(metadata: TmdbMovieMetadata) -> bool:
    """Return whether TMDB metadata strongly suggests a Japanese anime movie."""
    has_animation_genre = ANIMATION_GENRE_ID in metadata.genre_ids
    is_japanese = metadata.original_language == "ja" or "JP" in metadata.origin_country
    return has_animation_genre and is_japanese


def _apply_metadata(
    download_request: DownloadRequest,
    metadata: TmdbMovieMetadata,
) -> None:
    """Copy TMDB metadata onto a download request row."""
    download_request.genre_ids = metadata.genre_ids or [0]
    download_request.poster_path = metadata.poster_path
    download_request.backdrop_path = metadata.backdrop_path
    download_request.release_date = metadata.release_date
    download_request.release_year = metadata.release_year
    download_request.runtime = metadata.runtime
    download_request.title = metadata.title


def _index_queue_records(
    queue_records: list[dict],
) -> tuple[dict[int, dict], dict[int, dict]]:
    """Index Radarr queue records by TMDB ID and internal Radarr movie ID."""
    queue_by_tmdb_id: dict[int, dict] = {}
    queue_by_radarr_id: dict[int, dict] = {}

    for queue_record in queue_records:
        movie = queue_record.get("movie") or {}
        tmdb_id = _safe_int(movie.get("tmdbId"))
        radarr_movie_id = _safe_int(movie.get("id") or queue_record.get("movieId"))
        if tmdb_id is not None:
            queue_by_tmdb_id[tmdb_id] = queue_record
        if radarr_movie_id is not None:
            queue_by_radarr_id[radarr_movie_id] = queue_record

    return queue_by_tmdb_id, queue_by_radarr_id


def _apply_queue_record(
    download_request: DownloadRequest,
    queue_record: dict,
) -> None:
    """Copy Radarr queue state onto a local download request."""
    tracked_status = queue_record.get("trackedDownloadStatus")
    tracked_state = queue_record.get("trackedDownloadState")
    status_value = queue_record.get("status")
    error_message = _extract_queue_error(queue_record)

    download_request.download_title = queue_record.get("title")
    download_request.download_client = queue_record.get("downloadClient")
    download_request.quality = _extract_queue_quality(queue_record)
    download_request.size = _safe_int(queue_record.get("size"))
    download_request.size_left = _safe_int(queue_record.get("sizeleft"))
    download_request.time_left = queue_record.get("timeleft")
    download_request.tracked_download_status = tracked_status
    download_request.tracked_download_state = tracked_state

    if error_message:
        download_request.status = DOWNLOAD_STATUS_FAILED
        download_request.error_message = error_message[:500]
        return

    if _queue_record_is_active(status_value, tracked_status, tracked_state):
        download_request.status = DOWNLOAD_STATUS_DOWNLOADING
        download_request.error_message = None


def _mark_request_available(download_request: DownloadRequest) -> None:
    """Mark one request as available and clear transient queue details."""
    download_request.status = DOWNLOAD_STATUS_AVAILABLE
    download_request.error_message = None
    _clear_queue_fields(download_request)


def _clear_queue_fields(download_request: DownloadRequest) -> None:
    """Clear transient Radarr queue details from a request."""
    download_request.download_title = None
    download_request.download_client = None
    download_request.quality = None
    download_request.size = None
    download_request.size_left = None
    download_request.time_left = None
    download_request.tracked_download_status = None
    download_request.tracked_download_state = None


def _extract_queue_quality(queue_record: dict) -> str | None:
    """Extract the human-readable quality name from a Radarr queue record."""
    quality = queue_record.get("quality") or {}
    nested_quality = quality.get("quality") or {}
    return nested_quality.get("name") or quality.get("name")


def _extract_queue_error(queue_record: dict) -> str | None:
    """Return a meaningful Radarr queue error message, if present."""
    error_message = queue_record.get("errorMessage")
    if error_message:
        return str(error_message)

    tracked_status = str(queue_record.get("trackedDownloadStatus") or "").lower()
    status_value = str(queue_record.get("status") or "").lower()
    if tracked_status not in {"warning", "error"} and status_value not in {
        "warning",
        "error",
    }:
        return None

    status_messages = queue_record.get("statusMessages") or []
    for status_message in status_messages:
        messages = status_message.get("messages") or []
        if messages:
            return "; ".join(str(message) for message in messages)
        title = status_message.get("title")
        if title:
            return str(title)

    return "Radarr reported a download queue issue"


def _queue_record_is_active(
    status_value: str | None,
    tracked_status: str | None,
    tracked_state: str | None,
) -> bool:
    """Return whether a queue record indicates an active download lifecycle."""
    normalized_status = str(status_value or "").lower()
    normalized_tracked_status = str(tracked_status or "").lower()
    normalized_tracked_state = str(tracked_state or "").lower()
    return (
        normalized_tracked_status == "ok"
        or normalized_status in {"queued", "downloading", "completed"}
        or normalized_tracked_state in {"queued", "downloading", "importpending"}
    )


def _safe_int(value: object) -> int | None:
    """Coerce a value to int, returning None for invalid values."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_owned_movie(tmdb_id: int, database_session: Session) -> bool:
    """Return whether Scenario already marks the movie as owned."""
    return (
        database_session.query(OwnedMedia.id)
        .filter(
            OwnedMedia.tmdb_id == tmdb_id,
            OwnedMedia.media_type == MOVIE_MEDIA_TYPE,
            OwnedMedia.source == RADARR_SOURCE,
        )
        .first()
        is not None
    )


def _extract_radarr_movie_id(radarr_movie: dict) -> int | None:
    """Extract the Radarr internal movie ID from an add/search response."""
    radarr_movie_id = radarr_movie.get("id")
    if radarr_movie_id is None:
        return None
    try:
        return int(radarr_movie_id)
    except (TypeError, ValueError):
        return None


def _mark_request_failed(
    database_session: Session,
    download_request: DownloadRequest,
    error_message: str,
) -> None:
    """Mark a download request as failed and persist the error."""
    download_request.status = DOWNLOAD_STATUS_FAILED
    download_request.error_message = error_message[:500]
    database_session.commit()
