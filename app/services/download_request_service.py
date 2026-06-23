"""Download request service for Radarr movie requests."""

import re
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.database.session import SessionLocal
from app.models import DownloadRequest, OwnedMedia, User
from app.schemas import DownloadRequestResponse
from app.services.radarr_service import RadarrService
from app.services.sonarr_service import SonarrService
from app.services.tmdb_service import TmdbMovieMetadata, TmdbService, TmdbTvMetadata

RADARR_SOURCE = "RADARR"
SONARR_SOURCE = "SONARR"
MOVIE_MEDIA_TYPE = "movie"
TV_MEDIA_TYPE = "tv"
SCOPE_MOVIE = "movie"
SCOPE_SERIES = "series"
SCOPE_SEASON = "season"
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
SONARR_NOT_FOUND_GRACE_PERIOD = timedelta(minutes=5)
TERMINAL_DOWNLOAD_STATUSES = {
    DOWNLOAD_STATUS_FAILED,
    DOWNLOAD_STATUS_NOT_FOUND,
    DOWNLOAD_STATUS_CANCELLED,
    DOWNLOAD_STATUS_AVAILABLE,
}
RETRYABLE_DOWNLOAD_STATUSES = {
    DOWNLOAD_STATUS_FAILED,
    DOWNLOAD_STATUS_NOT_FOUND,
    DOWNLOAD_STATUS_CANCELLED,
}


def request_radarr_movie_download(
    tmdb_id: int,
    user: User,
    database_session: Session,
    background_tasks: BackgroundTasks | None = None,
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

    if background_tasks is not None:
        download_request = existing_request or _create_pending_download_request(
            tmdb_id,
            user,
            database_session,
        )
        download_request.status = DOWNLOAD_STATUS_REQUESTED
        download_request.error_message = None
        _clear_queue_fields(download_request)
        database_session.commit()
        background_tasks.add_task(process_radarr_movie_download_request, download_request.id)
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

    process_radarr_movie_download_request(download_request.id)
    database_session.refresh(download_request)
    return DownloadRequestResponse.model_validate(download_request)


def process_radarr_movie_download_request(request_id: UUID) -> None:
    """Trigger Radarr work for a local movie request using a fresh session."""
    database_session = SessionLocal()
    try:
        download_request = database_session.get(DownloadRequest, request_id)
        if download_request is None:
            return
        metadata = TmdbService().get_movie_metadata(download_request.tmdb_id)
        _apply_metadata(download_request, metadata)
        download_request.status = DOWNLOAD_STATUS_REQUESTED
        download_request.error_message = None
        _clear_queue_fields(download_request)
        database_session.commit()

        try:
            radarr_movie = RadarrService().add_movie_and_search(
                download_request.tmdb_id,
                tag_labels=_get_radarr_tag_labels(metadata),
            )
            download_request.radarr_movie_id = _extract_radarr_movie_id(radarr_movie)
            download_request.radarr_search_command_id = _extract_radarr_search_command_id(
                radarr_movie,
            )
            download_request.status = DOWNLOAD_STATUS_SEARCHING
            download_request.error_message = None
            _clear_queue_fields(download_request)
            database_session.commit()
        except HTTPException as error:
            _mark_request_failed(database_session, download_request, str(error.detail))
        except Exception as error:
            _mark_request_failed(database_session, download_request, str(error))
    finally:
        database_session.close()


def request_sonarr_series_download(
    tmdb_id: int,
    user: User,
    database_session: Session,
    background_tasks: BackgroundTasks | None = None,
) -> DownloadRequestResponse:
    """Create or reuse a Sonarr whole-series request and trigger search."""
    return _request_sonarr_download(
        tmdb_id,
        user,
        database_session,
        SCOPE_SERIES,
        background_tasks=background_tasks,
    )


def request_sonarr_season_download(
    tmdb_id: int,
    season_number: int,
    user: User,
    database_session: Session,
    background_tasks: BackgroundTasks | None = None,
) -> DownloadRequestResponse:
    """Create or reuse a Sonarr season request and trigger search."""
    return _request_sonarr_download(
        tmdb_id,
        user,
        database_session,
        SCOPE_SEASON,
        season_number,
        background_tasks=background_tasks,
    )


def retry_download_request(
    request_id: UUID,
    database_session: Session,
) -> DownloadRequestResponse:
    """Retry a failed, not-found, or cancelled Radarr movie request."""
    download_request = _get_download_request_or_404(request_id, database_session)
    if download_request.status not in RETRYABLE_DOWNLOAD_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Download request cannot be retried in its current state",
        )

    if download_request.source == SONARR_SOURCE:
        return _retry_sonarr_request(download_request, database_session)

    metadata = TmdbService().get_movie_metadata(download_request.tmdb_id)
    _apply_metadata(download_request, metadata)
    download_request.status = DOWNLOAD_STATUS_REQUESTED
    download_request.error_message = None
    _clear_queue_fields(download_request)
    database_session.commit()

    try:
        radarr_movie = RadarrService().add_movie_and_search(
            download_request.tmdb_id,
            tag_labels=_get_radarr_tag_labels(metadata),
        )
        download_request.radarr_movie_id = _extract_radarr_movie_id(radarr_movie)
        download_request.radarr_search_command_id = _extract_radarr_search_command_id(
            radarr_movie,
        )
        download_request.status = DOWNLOAD_STATUS_SEARCHING
        download_request.error_message = None
        _clear_queue_fields(download_request)
        database_session.commit()
    except HTTPException as error:
        _mark_request_failed(database_session, download_request, str(error.detail))
    except Exception as error:
        _mark_request_failed(database_session, download_request, str(error))

    return DownloadRequestResponse.model_validate(download_request)


def cancel_download_request(
    request_id: UUID,
    database_session: Session,
) -> DownloadRequestResponse:
    """Cancel a local request and remove its active Radarr queue/movie state."""
    download_request = _get_download_request_or_404(request_id, database_session)
    if download_request.source == SONARR_SOURCE:
        return _cancel_sonarr_request(download_request, database_session)

    radarr_service = RadarrService()

    queue_record = _find_queue_record_for_request(
        download_request,
        radarr_service.get_queue(),
    )
    if queue_record:
        queue_item_id = _safe_int(queue_record.get("id"))
        if queue_item_id is not None:
            radarr_service.delete_queue_item(queue_item_id)

    if download_request.radarr_movie_id is not None:
        radarr_service.delete_movie_if_unavailable(download_request.radarr_movie_id)

    download_request.status = DOWNLOAD_STATUS_CANCELLED
    download_request.error_message = None
    _clear_queue_fields(download_request)
    database_session.commit()

    return DownloadRequestResponse.model_validate(download_request)


def clean_download_requests(database_session: Session) -> int:
    """Remove terminal local download request history rows."""
    deleted_count = (
        database_session.query(DownloadRequest)
        .filter(DownloadRequest.status.in_(TERMINAL_DOWNLOAD_STATUSES))
        .delete(synchronize_session=False)
    )
    database_session.commit()
    return int(deleted_count)


def cancel_all_download_requests(database_session: Session) -> int:
    """Cancel all active download requests that can be cancelled."""
    request_ids = [
        request_id
        for (request_id,) in database_session.query(DownloadRequest.id)
        .filter(DownloadRequest.status.in_(ACTIVE_DOWNLOAD_STATUSES))
        .all()
    ]

    cancelled_count = 0
    for request_id in request_ids:
        try:
            cancel_download_request(request_id, database_session)
            cancelled_count += 1
        except HTTPException:
            continue

    return cancelled_count


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
    scope: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> DownloadRequestResponse | None:
    """Return the latest download request for a media item, if any."""
    reconcile_download_requests(database_session)
    if source := (SONARR_SOURCE if media_type == TV_MEDIA_TYPE else None):
        download_request = get_download_request_for_scope(
            tmdb_id,
            media_type,
            source,
            scope or SCOPE_SERIES,
            database_session,
            season_number,
            episode_number,
        )
    else:
        download_request = get_download_request_for_media(tmdb_id, media_type, database_session)
    if not download_request:
        return None
    return DownloadRequestResponse.model_validate(download_request)


def get_download_request_for_scope(
    tmdb_id: int,
    media_type: str,
    source: str,
    scope: str,
    database_session: Session,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> DownloadRequest | None:
    """Return the latest request for a scoped media item."""
    query = database_session.query(DownloadRequest).filter(
        DownloadRequest.tmdb_id == tmdb_id,
        DownloadRequest.media_type == media_type,
        DownloadRequest.source == source,
        DownloadRequest.scope == scope,
    )
    if season_number is not None:
        query = query.filter(DownloadRequest.season_number == season_number)
    if episode_number is not None:
        query = query.filter(DownloadRequest.episode_number == episode_number)
    return query.order_by(DownloadRequest.requested_at.desc()).first()


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


def mark_radarr_movie_request_grabbed(
    tmdb_id: int,
    payload_data: dict,
    database_session: Session,
) -> int:
    """Mark matching active requests as downloading after Radarr grabs a release."""
    download_requests = (
        database_session.query(DownloadRequest)
        .filter(
            DownloadRequest.tmdb_id == tmdb_id,
            DownloadRequest.media_type == MOVIE_MEDIA_TYPE,
            DownloadRequest.source == RADARR_SOURCE,
            DownloadRequest.status.in_(ACTIVE_DOWNLOAD_STATUSES),
        )
        .all()
    )

    for download_request in download_requests:
        download_request.status = DOWNLOAD_STATUS_DOWNLOADING
        download_request.error_message = None
        download_request.download_title = _extract_grab_title(payload_data)
        download_request.quality = _extract_grab_quality(payload_data)
        download_request.tracked_download_status = "ok"
        download_request.tracked_download_state = "grabbed"

    return len(download_requests)


def mark_sonarr_request_grabbed(
    tmdb_id: int,
    season_number: int | None,
    payload_data: dict,
    database_session: Session,
) -> int:
    """Mark matching active Sonarr requests as downloading after a grab webhook."""
    query = database_session.query(DownloadRequest).filter(
        DownloadRequest.tmdb_id == tmdb_id,
        DownloadRequest.media_type == TV_MEDIA_TYPE,
        DownloadRequest.source == SONARR_SOURCE,
        DownloadRequest.status.in_(ACTIVE_DOWNLOAD_STATUSES),
    )
    download_requests = query.all()

    updated_count = 0
    for download_request in download_requests:
        if download_request.scope == SCOPE_SEASON and season_number != download_request.season_number:
            continue
        download_request.status = DOWNLOAD_STATUS_DOWNLOADING
        download_request.error_message = None
        download_request.download_title = _extract_grab_title(payload_data)
        download_request.quality = _extract_grab_quality(payload_data)
        download_request.tracked_download_status = "ok"
        download_request.tracked_download_state = "grabbed"
        updated_count += 1

    return updated_count


def refresh_sonarr_request_availability(
    tmdb_id: int,
    database_session: Session,
) -> int:
    """Mark completed Sonarr requests available when their scope is fully owned."""
    download_requests = (
        database_session.query(DownloadRequest)
        .filter(
            DownloadRequest.tmdb_id == tmdb_id,
            DownloadRequest.media_type == TV_MEDIA_TYPE,
            DownloadRequest.source == SONARR_SOURCE,
            DownloadRequest.status != DOWNLOAD_STATUS_AVAILABLE,
        )
        .all()
    )
    updated_count = 0
    for download_request in download_requests:
        if _sonarr_request_scope_available(download_request, database_session):
            _mark_request_available(download_request)
            updated_count += 1
    return updated_count


def reconcile_download_requests(database_session: Session) -> None:
    """Refresh active download requests from owned media and Radarr queue."""
    _reconcile_radarr_download_requests(database_session)
    _reconcile_sonarr_download_requests(database_session)


def _reconcile_radarr_download_requests(database_session: Session) -> None:
    """Refresh active Radarr movie requests from owned media and queue."""
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
            radarr_service = RadarrService()
            queue_records = radarr_service.get_queue()
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
            else:
                _apply_radarr_history_or_command_state(download_request, radarr_service)

    database_session.commit()


def _reconcile_sonarr_download_requests(database_session: Session) -> None:
    """Refresh active Sonarr TV requests from owned media and queue."""
    active_requests = (
        database_session.query(DownloadRequest)
        .filter(
            DownloadRequest.media_type == TV_MEDIA_TYPE,
            DownloadRequest.source == SONARR_SOURCE,
            DownloadRequest.status.in_(ACTIVE_DOWNLOAD_STATUSES),
        )
        .all()
    )
    if not active_requests:
        return

    pending_requests: list[DownloadRequest] = []
    for download_request in active_requests:
        if _sonarr_request_scope_available(download_request, database_session):
            _mark_request_available(download_request)
        else:
            pending_requests.append(download_request)

    if pending_requests:
        try:
            sonarr_service = SonarrService()
            queue_records = sonarr_service.get_queue()
        except HTTPException:
            database_session.commit()
            return
        episode_maps: dict[int, dict[int, tuple[int | None, int | None]]] = {}
        for download_request in pending_requests:
            episode_map = _get_sonarr_episode_map_for_request(
                sonarr_service,
                download_request,
                episode_maps,
            )
            _sync_sonarr_owned_episodes_for_request(
                sonarr_service,
                download_request,
                database_session,
            )
            if _sonarr_request_scope_available(download_request, database_session):
                _mark_request_available(download_request)
                continue
            matching_records = _find_sonarr_queue_records_for_request(
                download_request,
                queue_records,
                episode_map,
            )
            if matching_records:
                _apply_sonarr_queue_records(download_request, matching_records)
            else:
                _apply_sonarr_history_or_command_state(
                    download_request,
                    sonarr_service,
                    episode_map,
                )

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
        scope=SCOPE_MOVIE,
        source=RADARR_SOURCE,
        status=DOWNLOAD_STATUS_REQUESTED,
        requested_at=requested_at,
    )
    _apply_metadata(download_request, metadata)
    database_session.add(download_request)
    database_session.flush()
    return download_request


def _create_pending_download_request(
    tmdb_id: int,
    user: User,
    database_session: Session,
) -> DownloadRequest:
    """Create a lightweight movie request row for background hydration."""
    download_request = DownloadRequest(
        user_id=user.id,
        tmdb_id=tmdb_id,
        media_type=MOVIE_MEDIA_TYPE,
        scope=SCOPE_MOVIE,
        source=RADARR_SOURCE,
        status=DOWNLOAD_STATUS_REQUESTED,
        genre_ids=[0],
        poster_path="",
        backdrop_path="",
        release_date="",
        release_year="",
        runtime=0,
        title="",
        requested_at=datetime.utcnow(),
    )
    database_session.add(download_request)
    database_session.flush()
    return download_request


def _request_sonarr_download(
    tmdb_id: int,
    user: User,
    database_session: Session,
    scope: str,
    season_number: int | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> DownloadRequestResponse:
    """Create or reuse a scoped Sonarr request and trigger search."""
    existing_request = get_download_request_for_scope(
        tmdb_id,
        TV_MEDIA_TYPE,
        SONARR_SOURCE,
        scope,
        database_session,
        season_number,
    )
    if existing_request and existing_request.status in ACTIVE_DOWNLOAD_STATUSES:
        return DownloadRequestResponse.model_validate(existing_request)

    if background_tasks is not None:
        download_request = existing_request or _create_pending_sonarr_download_request(
            tmdb_id,
            user,
            database_session,
            scope,
            season_number,
        )
        download_request.scope = scope
        download_request.season_number = season_number
        download_request.status = DOWNLOAD_STATUS_REQUESTED
        download_request.error_message = None
        _clear_queue_fields(download_request)
        database_session.commit()
        background_tasks.add_task(process_sonarr_download_request, download_request.id)
        return DownloadRequestResponse.model_validate(download_request)

    metadata = TmdbService().get_tv_metadata(tmdb_id)
    download_request = existing_request or _create_sonarr_download_request(
        tmdb_id,
        user,
        database_session,
        metadata,
        scope,
        season_number,
    )
    _apply_metadata(download_request, metadata)
    download_request.scope = scope
    download_request.season_number = season_number
    download_request.status = DOWNLOAD_STATUS_REQUESTED
    download_request.error_message = None
    _clear_queue_fields(download_request)
    database_session.commit()

    process_sonarr_download_request(download_request.id)
    database_session.refresh(download_request)
    return DownloadRequestResponse.model_validate(download_request)


def process_sonarr_download_request(request_id: UUID) -> None:
    """Trigger Sonarr work for a local TV request using a fresh session."""
    database_session = SessionLocal()
    try:
        download_request = database_session.get(DownloadRequest, request_id)
        if download_request is None:
            return
        scope = download_request.scope
        season_number = download_request.season_number

        metadata = TmdbService().get_tv_metadata(download_request.tmdb_id)
        _apply_metadata(download_request, metadata)
        download_request.status = DOWNLOAD_STATUS_REQUESTED
        download_request.error_message = None
        _clear_queue_fields(download_request)
        database_session.commit()

        tvdb_id = TmdbService().get_tvdb_id_for_tv(download_request.tmdb_id)
        if tvdb_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="TMDB TV series does not have a TVDB ID",
            )
        is_anime = _is_anime_tv(metadata)
        use_on_air_profile = _sonarr_request_uses_on_air_profile(
            download_request.tmdb_id,
            scope,
            season_number,
        )
        sonarr_service = SonarrService()
        sonarr_series = sonarr_service.add_series_and_search(
            tvdb_id=tvdb_id,
            tmdb_id=download_request.tmdb_id,
            season_number=season_number,
            is_anime=is_anime,
            use_on_air_profile=use_on_air_profile,
            tag_labels=_get_sonarr_tag_labels(metadata),
        )
        download_request.tvdb_id = tvdb_id
        download_request.sonarr_series_id = _extract_sonarr_series_id(sonarr_series)
        download_request.sonarr_search_command_id = _safe_int(
            sonarr_series.get("_scenario_search_command_id"),
        )
        _sync_sonarr_owned_episodes_for_request(
            sonarr_service,
            download_request,
            database_session,
        )
        if scope == SCOPE_SERIES and download_request.sonarr_search_command_id is None:
            if _sonarr_request_scope_available(download_request, database_session):
                _mark_request_available(download_request)
            else:
                download_request.status = DOWNLOAD_STATUS_NOT_FOUND
                download_request.error_message = "No missing aired episodes were found by Sonarr"
        else:
            download_request.status = DOWNLOAD_STATUS_SEARCHING
            download_request.error_message = None
        _clear_queue_fields(download_request)
        database_session.commit()
    except HTTPException as error:
        _mark_request_failed(database_session, download_request, str(error.detail))
    except Exception as error:
        _mark_request_failed(database_session, download_request, str(error))
    finally:
        database_session.close()


def _create_sonarr_download_request(
    tmdb_id: int,
    user: User,
    database_session: Session,
    metadata: TmdbTvMetadata,
    scope: str,
    season_number: int | None = None,
) -> DownloadRequest:
    """Create a hydrated local Sonarr download request row."""
    download_request = DownloadRequest(
        user_id=user.id,
        tmdb_id=tmdb_id,
        media_type=TV_MEDIA_TYPE,
        scope=scope,
        source=SONARR_SOURCE,
        status=DOWNLOAD_STATUS_REQUESTED,
        season_number=season_number,
        requested_at=datetime.utcnow(),
    )
    _apply_metadata(download_request, metadata)
    database_session.add(download_request)
    database_session.flush()
    return download_request


def _create_pending_sonarr_download_request(
    tmdb_id: int,
    user: User,
    database_session: Session,
    scope: str,
    season_number: int | None = None,
) -> DownloadRequest:
    """Create a lightweight Sonarr request row for background hydration."""
    download_request = DownloadRequest(
        user_id=user.id,
        tmdb_id=tmdb_id,
        media_type=TV_MEDIA_TYPE,
        scope=scope,
        source=SONARR_SOURCE,
        status=DOWNLOAD_STATUS_REQUESTED,
        season_number=season_number,
        genre_ids=[0],
        poster_path="",
        backdrop_path="",
        release_date="",
        release_year="",
        runtime=0,
        title="",
        requested_at=datetime.utcnow(),
    )
    database_session.add(download_request)
    database_session.flush()
    return download_request


def _retry_sonarr_request(
    download_request: DownloadRequest,
    database_session: Session,
) -> DownloadRequestResponse:
    """Retry a failed, not-found, or cancelled Sonarr request."""
    if download_request.status not in RETRYABLE_DOWNLOAD_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Download request cannot be retried in its current state",
        )
    user = download_request.requester
    if not user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request has no requester")
    return _request_sonarr_download(
        download_request.tmdb_id,
        user,
        database_session,
        download_request.scope,
        download_request.season_number,
    )


def _cancel_sonarr_request(
    download_request: DownloadRequest,
    database_session: Session,
) -> DownloadRequestResponse:
    """Cancel a local Sonarr request and remove matching active queue state."""
    sonarr_service = SonarrService()
    try:
        episode_maps: dict[int, dict[int, tuple[int | None, int | None]]] = {}
        episode_map = _get_sonarr_episode_map_for_request(
            sonarr_service,
            download_request,
            episode_maps,
        )
        queue_records = _find_sonarr_queue_records_for_request(
            download_request,
            sonarr_service.get_queue(),
            episode_map,
        )
        for queue_record in queue_records:
            queue_item_id = _safe_int(queue_record.get("id"))
            if queue_item_id is not None:
                sonarr_service.delete_queue_item(queue_item_id)
        if download_request.sonarr_series_id is not None:
            sonarr_service.delete_series_if_unavailable(download_request.sonarr_series_id)
    except HTTPException:
        pass

    download_request.status = DOWNLOAD_STATUS_CANCELLED
    download_request.error_message = None
    _clear_queue_fields(download_request)
    database_session.commit()
    return DownloadRequestResponse.model_validate(download_request)


def _get_radarr_tag_labels(metadata: TmdbMovieMetadata) -> list[str]:
    """Return Radarr tags Scenario should apply for a movie request."""
    if _is_anime_movie(metadata):
        return [ANIME_TAG_LABEL]
    return []


def _get_sonarr_tag_labels(metadata: TmdbTvMetadata) -> list[str]:
    """Return Sonarr tags Scenario should apply for a TV request."""
    if _is_anime_tv(metadata):
        return [settings.SONARR_ANIME_TAG_LABEL]
    return []


def _is_anime_movie(metadata: TmdbMovieMetadata) -> bool:
    """Return whether TMDB metadata strongly suggests a Japanese anime movie."""
    has_animation_genre = ANIMATION_GENRE_ID in metadata.genre_ids
    is_japanese = metadata.original_language == "ja" or "JP" in metadata.origin_country
    return has_animation_genre and is_japanese


def _is_anime_tv(metadata: TmdbTvMetadata) -> bool:
    """Return whether TMDB metadata strongly suggests a Japanese anime TV show."""
    has_animation_genre = ANIMATION_GENRE_ID in metadata.genre_ids
    is_japanese = metadata.original_language == "ja" or "JP" in metadata.origin_country
    return has_animation_genre and is_japanese


def _sonarr_request_uses_on_air_profile(
    tmdb_id: int,
    scope: str,
    season_number: int | None,
) -> bool:
    """Return whether a Sonarr request should use the on-air TV profile."""
    try:
        tmdb_service = TmdbService()
        if scope == SCOPE_SEASON:
            if season_number is None:
                return True
            return _tmdb_season_is_current(tmdb_service, tmdb_id, season_number)

        tv_details = tmdb_service.get_tv_details(tmdb_id)
        for season in tv_details.get("seasons", []) or []:
            current_season_number = _safe_int(season.get("season_number"))
            if current_season_number is None or current_season_number <= 0:
                continue
            if _tmdb_season_is_current(tmdb_service, tmdb_id, current_season_number):
                return True
    except Exception:
        return True
    return False


def _tmdb_season_is_current(
    tmdb_service: TmdbService,
    tmdb_id: int,
    season_number: int,
) -> bool:
    """Return whether a TMDB season has unaired or recently aired episodes."""
    season_details = tmdb_service.get_tv_season_details(tmdb_id, season_number)
    today = datetime.utcnow().date()
    recent_cutoff = today - timedelta(days=settings.SONARR_ON_AIR_RECENCY_DAYS)
    latest_aired_at = None

    for episode in season_details.get("episodes", []) or []:
        air_date = episode.get("air_date") or ""
        if not air_date:
            continue
        try:
            aired_at = datetime.fromisoformat(air_date).date()
        except ValueError:
            continue
        if aired_at > today:
            return True
        if latest_aired_at is None or aired_at > latest_aired_at:
            latest_aired_at = aired_at

    return latest_aired_at is not None and latest_aired_at >= recent_cutoff


def _apply_metadata(
    download_request: DownloadRequest,
    metadata: TmdbMovieMetadata | TmdbTvMetadata,
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


def _apply_radarr_history_or_command_state(
    download_request: DownloadRequest,
    radarr_service: RadarrService,
) -> None:
    """Use Radarr history/command state when a request is absent from queue."""
    try:
        history_records = radarr_service.get_history()
    except HTTPException:
        history_records = []

    history_record = _find_history_record_for_request(
        download_request,
        history_records,
    )
    if history_record:
        event_type = str(history_record.get("eventType") or "").lower()
        if event_type in {"grabbed", "downloadfolderimported", "moviefileimported"}:
            download_request.status = DOWNLOAD_STATUS_DOWNLOADING
            download_request.download_title = history_record.get("sourceTitle")
            download_request.quality = _extract_queue_quality(history_record)
            download_request.error_message = None
            return
        if event_type in {"downloadfailed", "moviefiledeleted"}:
            download_request.status = DOWNLOAD_STATUS_FAILED
            download_request.error_message = "Radarr reported a failed download"
            return

    if _search_command_finished(download_request, radarr_service):
        download_request.status = DOWNLOAD_STATUS_NOT_FOUND
        download_request.error_message = None


def _apply_sonarr_command_state(
    download_request: DownloadRequest,
    sonarr_service: SonarrService,
) -> None:
    """Use Sonarr command state when a request is absent from queue."""
    command_id = download_request.sonarr_search_command_id
    if command_id is None:
        return
    command = sonarr_service.get_command(command_id)
    if not command:
        return
    status_value = str(command.get("status") or "").lower()
    state_value = str(command.get("state") or "").lower()
    if status_value in {"completed", "failed"} or state_value in {"completed", "failed"}:
        if datetime.utcnow() - download_request.requested_at < SONARR_NOT_FOUND_GRACE_PERIOD:
            download_request.status = DOWNLOAD_STATUS_SEARCHING
            download_request.error_message = None
            return
        download_request.status = DOWNLOAD_STATUS_NOT_FOUND
        download_request.error_message = (
            "Sonarr completed the search but did not grab any matching release."
        )


def _apply_sonarr_history_or_command_state(
    download_request: DownloadRequest,
    sonarr_service: SonarrService,
    episode_map: dict[int, tuple[int | None, int | None]] | None = None,
) -> None:
    """Use Sonarr history before treating a completed command as not found."""
    history_record = _find_sonarr_history_record_for_request(
        download_request,
        _get_sonarr_history_records(download_request, sonarr_service),
        episode_map,
    )
    if history_record:
        event_type = str(history_record.get("eventType") or "").lower()
        if event_type in {"grabbed", "downloadfolderimported", "episodefileimported"}:
            _apply_sonarr_history_record(download_request, history_record)
            return
        if event_type in {"downloadfailed", "episodefiledeleted"}:
            download_request.status = DOWNLOAD_STATUS_FAILED
            download_request.error_message = "Sonarr reported a failed download"
            return

    _apply_sonarr_command_state(download_request, sonarr_service)


def _sync_sonarr_owned_episodes_for_request(
    sonarr_service: SonarrService,
    download_request: DownloadRequest,
    database_session: Session,
) -> None:
    """Refresh local owned episodes for one Sonarr series during reconciliation."""
    sonarr_series_id = download_request.sonarr_series_id
    tvdb_id = download_request.tvdb_id
    if sonarr_series_id is None or tvdb_id is None:
        return

    try:
        episodes = sonarr_service.get_episodes(sonarr_series_id)
        metadata = TmdbService().get_tv_metadata(download_request.tmdb_id)
    except Exception:
        return

    synced_at = datetime.utcnow()
    owned_rows: list[OwnedMedia] = []
    for episode in episodes:
        season_number = _safe_int(episode.get("seasonNumber"))
        episode_number = _safe_int(episode.get("episodeNumber"))
        if episode.get("hasFile") is not True or not season_number or season_number <= 0:
            continue
        if episode_number is None:
            continue
        owned_rows.append(
            OwnedMedia(
                tmdb_id=download_request.tmdb_id,
                media_type=TV_MEDIA_TYPE,
                scope="episode",
                tvdb_id=tvdb_id,
                sonarr_series_id=sonarr_series_id,
                season_number=season_number,
                episode_number=episode_number,
                episode_title=episode.get("title") or "",
                episode_air_date=episode.get("airDate") or episode.get("airDateUtc") or "",
                genre_ids=metadata.genre_ids or [0],
                poster_path=metadata.poster_path,
                backdrop_path=metadata.backdrop_path,
                release_date=metadata.release_date,
                release_year=metadata.release_year,
                runtime=metadata.runtime,
                title=metadata.title,
                source=SONARR_SOURCE,
                last_synced_at=synced_at,
                metadata_synced_at=synced_at,
            )
        )

    database_session.query(OwnedMedia).filter(
        OwnedMedia.tmdb_id == download_request.tmdb_id,
        OwnedMedia.media_type == TV_MEDIA_TYPE,
        OwnedMedia.source == SONARR_SOURCE,
        OwnedMedia.scope == "episode",
    ).delete(synchronize_session=False)
    database_session.add_all(owned_rows)


def _find_sonarr_queue_records_for_request(
    download_request: DownloadRequest,
    queue_records: list[dict],
    episode_map: dict[int, tuple[int | None, int | None]] | None = None,
) -> list[dict]:
    """Find Sonarr queue records matching a local request."""
    records: list[dict] = []
    for queue_record in queue_records:
        series = queue_record.get("series") or {}
        series_id = _safe_int(series.get("id") or queue_record.get("seriesId"))
        tvdb_id = _safe_int(series.get("tvdbId"))

        if not _sonarr_series_matches(download_request, series_id, tvdb_id):
            if not _sonarr_record_title_matches_request(download_request, queue_record):
                continue
        if _sonarr_record_title_matches_request(download_request, queue_record):
            records.append(queue_record)
            continue
        if download_request.scope == SCOPE_SEASON and download_request.season_number not in _sonarr_record_season_numbers(
            queue_record,
            episode_map,
        ):
            continue
        records.append(queue_record)
    return records


def _sonarr_record_title_matches_request(
    download_request: DownloadRequest,
    record: dict,
) -> bool:
    """Return whether a Sonarr queue/history title belongs to a request.

    Season packs can have sparse queue metadata in Sonarr v3. Matching a recent
    queue item back to the last grabbed title keeps progress updates aligned
    with the same release Sonarr already accepted for this request.
    """
    request_title = _normalize_release_title(download_request.download_title)
    if not request_title:
        return False

    candidate_titles = [
        record.get("title"),
        record.get("sourceTitle"),
        (record.get("data") or {}).get("sourceTitle"),
    ]
    return any(_normalize_release_title(title) == request_title for title in candidate_titles)


def _normalize_release_title(value: object) -> str:
    """Normalize release titles for exact-ish queue/history matching."""
    return str(value or "").strip().lower().replace("[tgx]", "")


def _get_sonarr_episode_map_for_request(
    sonarr_service: SonarrService,
    download_request: DownloadRequest,
    episode_maps: dict[int, dict[int, tuple[int | None, int | None]]],
) -> dict[int, tuple[int | None, int | None]] | None:
    """Return cached episode ID mapping for a Sonarr request series."""
    sonarr_series_id = download_request.sonarr_series_id
    if sonarr_series_id is None:
        return None
    if sonarr_series_id not in episode_maps:
        try:
            episode_maps[sonarr_series_id] = _build_sonarr_episode_map(
                sonarr_service.get_episodes(sonarr_series_id),
            )
        except HTTPException:
            episode_maps[sonarr_series_id] = {}
    return episode_maps[sonarr_series_id]


def _build_sonarr_episode_map(
    episodes: list[dict],
) -> dict[int, tuple[int | None, int | None]]:
    """Build a Sonarr episode ID to season/episode number map."""
    episode_map: dict[int, tuple[int | None, int | None]] = {}
    for episode in episodes:
        episode_id = _safe_int(episode.get("id"))
        if episode_id is None:
            continue
        episode_map[episode_id] = (
            _safe_int(episode.get("seasonNumber")),
            _safe_int(episode.get("episodeNumber")),
        )
    return episode_map


def _get_sonarr_history_records(
    download_request: DownloadRequest,
    sonarr_service: SonarrService,
) -> list[dict]:
    """Fetch Sonarr history records most relevant to a request."""
    try:
        if download_request.sonarr_series_id is not None:
            return sonarr_service.get_history_for_series(download_request.sonarr_series_id)
        return sonarr_service.get_history()
    except HTTPException:
        return []


def _find_sonarr_history_record_for_request(
    download_request: DownloadRequest,
    history_records: list[dict],
    episode_map: dict[int, tuple[int | None, int | None]] | None = None,
) -> dict | None:
    """Find the most recent Sonarr history record matching a local request."""
    for history_record in history_records:
        series = history_record.get("series") or {}
        series_id = _safe_int(series.get("id") or history_record.get("seriesId"))
        tvdb_id = _safe_int(series.get("tvdbId"))
        if not _sonarr_series_matches(download_request, series_id, tvdb_id):
            continue
        if download_request.scope == SCOPE_SEASON and download_request.season_number not in _sonarr_record_season_numbers(
            history_record,
            episode_map,
        ):
            continue
        return history_record
    return None


def _sonarr_series_matches(
    download_request: DownloadRequest,
    series_id: int | None,
    tvdb_id: int | None,
) -> bool:
    """Return whether a Sonarr record belongs to a local TV request."""
    if download_request.sonarr_series_id is not None and series_id == download_request.sonarr_series_id:
        return True
    return download_request.tvdb_id is not None and tvdb_id == download_request.tvdb_id


def _sonarr_record_season_numbers(
    record: dict,
    episode_map: dict[int, tuple[int | None, int | None]] | None = None,
) -> set[int]:
    """Extract season numbers from Sonarr queue/history records."""
    season_numbers: set[int] = set()

    episode = record.get("episode") or {}
    data = record.get("data") or {}
    season_number = _safe_int(
        episode.get("seasonNumber") or record.get("seasonNumber") or data.get("seasonNumber"),
    )
    if season_number is not None:
        season_numbers.add(season_number)

    title_season_number = _extract_season_number_from_title(
        record.get("title") or record.get("sourceTitle") or data.get("sourceTitle"),
    )
    if title_season_number is not None:
        season_numbers.add(title_season_number)

    for nested_episode in record.get("episodes") or []:
        nested_season_number = _safe_int(nested_episode.get("seasonNumber"))
        if nested_season_number is not None:
            season_numbers.add(nested_season_number)

    for episode_id in _sonarr_record_episode_ids(record):
        mapped_episode = episode_map.get(episode_id) if episode_map else None
        if mapped_episode and mapped_episode[0] is not None:
            season_numbers.add(mapped_episode[0])

    return season_numbers


def _extract_season_number_from_title(value: object) -> int | None:
    """Extract an Sxx season number from a release title when metadata is sparse."""
    match = re.search(r"\bS(\d{1,2})\b", str(value or ""), re.IGNORECASE)
    if not match:
        return None
    return _safe_int(match.group(1))


def _sonarr_record_episode_ids(record: dict) -> set[int]:
    """Extract episode IDs from Sonarr queue/history records."""
    episode_ids: set[int] = set()
    episode = record.get("episode") or {}
    data = record.get("data") or {}
    episode_id = _safe_int(episode.get("id") or record.get("episodeId") or data.get("episodeId"))
    if episode_id is not None:
        episode_ids.add(episode_id)

    for raw_episode_id in record.get("episodeIds") or []:
        parsed_episode_id = _safe_int(raw_episode_id)
        if parsed_episode_id is not None:
            episode_ids.add(parsed_episode_id)

    for raw_episode_id in data.get("episodeIds") or []:
        parsed_episode_id = _safe_int(raw_episode_id)
        if parsed_episode_id is not None:
            episode_ids.add(parsed_episode_id)

    for nested_episode in record.get("episodes") or []:
        nested_episode_id = _safe_int(nested_episode.get("id"))
        if nested_episode_id is not None:
            episode_ids.add(nested_episode_id)

    return episode_ids


def _apply_sonarr_history_record(
    download_request: DownloadRequest,
    history_record: dict,
) -> None:
    """Copy Sonarr history state onto a local download request."""
    data = history_record.get("data") or {}
    download_request.status = DOWNLOAD_STATUS_DOWNLOADING
    download_request.error_message = None
    download_request.download_title = history_record.get("sourceTitle") or data.get("sourceTitle")
    download_request.download_client = data.get("downloadClientName") or data.get("downloadClient")
    download_request.quality = _extract_queue_quality(history_record)
    download_request.size = _safe_int(data.get("size"))
    download_request.tracked_download_status = "ok"
    download_request.tracked_download_state = "grabbed"


def _apply_sonarr_queue_records(
    download_request: DownloadRequest,
    queue_records: list[dict],
) -> None:
    """Aggregate Sonarr queue state onto a local download request."""
    if not queue_records:
        return
    unique_records = _dedupe_sonarr_queue_records(queue_records)
    first_record = unique_records[0]
    error_message = _extract_queue_error(first_record)
    download_request.download_title = (
        first_record.get("title") if len(unique_records) == 1 else f"{len(unique_records)} downloads active"
    )
    download_request.download_client = first_record.get("downloadClient")
    download_request.quality = _extract_queue_quality(first_record)
    download_request.size = sum(_safe_int(record.get("size")) or 0 for record in unique_records)
    download_request.size_left = sum(_safe_int(record.get("sizeleft")) or 0 for record in unique_records)
    download_request.time_left = first_record.get("timeleft")
    download_request.tracked_download_status = first_record.get("trackedDownloadStatus")
    download_request.tracked_download_state = first_record.get("trackedDownloadState")

    if error_message:
        if _queue_record_is_active(
            first_record.get("status"),
            first_record.get("trackedDownloadStatus"),
            first_record.get("trackedDownloadState"),
        ):
            download_request.status = DOWNLOAD_STATUS_DOWNLOADING
            download_request.error_message = error_message[:500]
            return
        download_request.status = DOWNLOAD_STATUS_FAILED
        download_request.error_message = error_message[:500]
        return

    download_request.status = DOWNLOAD_STATUS_DOWNLOADING
    download_request.error_message = None


def _dedupe_sonarr_queue_records(queue_records: list[dict]) -> list[dict]:
    """Deduplicate Sonarr queue rows that point to the same download.

    Sonarr can expose a season pack as one row per episode while each row
    repeats the same torrent size. Summing those rows overstates progress by
    the episode count, so aggregate by stable download identity first.
    """
    unique_records: list[dict] = []
    seen_keys: set[str] = set()
    for record in queue_records:
        key = _sonarr_queue_record_download_key(record)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_records.append(record)
    return unique_records


def _sonarr_queue_record_download_key(record: dict) -> str:
    """Return a stable identity for one Sonarr queue download item."""
    data = record.get("data") or {}
    for value in (
        record.get("downloadId"),
        record.get("downloadClientId"),
        data.get("downloadId"),
        data.get("downloadClientId"),
        record.get("outputPath"),
        record.get("title"),
    ):
        normalized_value = str(value or "").strip().lower()
        if normalized_value:
            return normalized_value
    return str(record.get("id") or "")


def _search_command_finished(
    download_request: DownloadRequest,
    radarr_service: RadarrService,
) -> bool:
    """Return whether Radarr says the tracked search command completed."""
    command_id = download_request.radarr_search_command_id
    if command_id is None:
        return False

    command = radarr_service.get_command(command_id)
    if not command:
        return False

    status_value = str(command.get("status") or "").lower()
    state_value = str(command.get("state") or "").lower()
    return status_value in {"completed", "failed"} or state_value in {
        "completed",
        "failed",
    }


def _find_queue_record_for_request(
    download_request: DownloadRequest,
    queue_records: list[dict],
) -> dict | None:
    """Find the Radarr queue record matching a local request."""
    queue_by_tmdb_id, queue_by_radarr_id = _index_queue_records(queue_records)
    queue_record = queue_by_tmdb_id.get(download_request.tmdb_id)
    if queue_record:
        return queue_record
    if download_request.radarr_movie_id is None:
        return None
    return queue_by_radarr_id.get(download_request.radarr_movie_id)


def _find_history_record_for_request(
    download_request: DownloadRequest,
    history_records: list[dict],
) -> dict | None:
    """Find the most recent Radarr history record matching a local request."""
    for history_record in history_records:
        movie = history_record.get("movie") or {}
        tmdb_id = _safe_int(movie.get("tmdbId"))
        radarr_movie_id = _safe_int(movie.get("id") or history_record.get("movieId"))
        if tmdb_id == download_request.tmdb_id:
            return history_record
        if (
            download_request.radarr_movie_id is not None
            and radarr_movie_id == download_request.radarr_movie_id
        ):
            return history_record
    return None


def _get_download_request_or_404(
    request_id: UUID,
    database_session: Session,
) -> DownloadRequest:
    """Return a download request or raise a 404 HTTP error."""
    download_request = (
        database_session.query(DownloadRequest)
        .filter(DownloadRequest.id == request_id)
        .first()
    )
    if not download_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download request not found",
        )
    return download_request


def _extract_grab_title(payload_data: dict) -> str | None:
    """Extract release title from a Radarr grab webhook payload."""
    release = payload_data.get("release") or {}
    return (
        payload_data.get("releaseTitle")
        or payload_data.get("sourceTitle")
        or release.get("releaseTitle")
        or release.get("title")
    )


def _extract_grab_quality(payload_data: dict) -> str | None:
    """Extract quality name from a Radarr grab webhook payload."""
    quality = payload_data.get("quality") or {}
    if isinstance(quality, str):
        return quality
    nested_quality = quality.get("quality") or {}
    return nested_quality.get("name") or quality.get("name")


def _mark_request_available(download_request: DownloadRequest) -> None:
    """Mark one request as available and clear transient queue details."""
    download_request.status = DOWNLOAD_STATUS_AVAILABLE
    download_request.error_message = None
    _clear_queue_fields(download_request)


def _sonarr_request_scope_available(
    download_request: DownloadRequest,
    database_session: Session,
) -> bool:
    """Return whether all aired episodes for a request scope are owned."""
    try:
        aired_episodes = _get_aired_tmdb_episodes_for_request(download_request)
    except Exception:
        return False
    if not aired_episodes:
        return False

    owned_episodes = {
        (owned.season_number, owned.episode_number)
        for owned in database_session.query(OwnedMedia)
        .filter(
            OwnedMedia.tmdb_id == download_request.tmdb_id,
            OwnedMedia.media_type == TV_MEDIA_TYPE,
            OwnedMedia.source == SONARR_SOURCE,
            OwnedMedia.scope == "episode",
        )
        .all()
    }
    return all(episode_key in owned_episodes for episode_key in aired_episodes)


def _get_aired_tmdb_episodes_for_request(
    download_request: DownloadRequest,
) -> set[tuple[int, int]]:
    """Return aired regular TMDB episode keys for a Sonarr request scope."""
    tmdb_service = TmdbService()
    season_numbers: list[int]
    if download_request.scope == SCOPE_SEASON:
        if download_request.season_number is None:
            return set()
        season_numbers = [download_request.season_number]
    else:
        tv_details = tmdb_service.get_tv_details(download_request.tmdb_id)
        season_numbers = [
            int(season.get("season_number"))
            for season in tv_details.get("seasons", [])
            if season.get("season_number") and int(season.get("season_number")) > 0
        ]

    episode_keys: set[tuple[int, int]] = set()
    today = datetime.utcnow().date()
    for season_number in season_numbers:
        season_details = tmdb_service.get_tv_season_details(download_request.tmdb_id, season_number)
        for episode in season_details.get("episodes", []) or []:
            episode_number = _safe_int(episode.get("episode_number"))
            air_date = episode.get("air_date") or ""
            if episode_number is None or not air_date:
                continue
            try:
                aired_at = datetime.fromisoformat(air_date).date()
            except ValueError:
                continue
            if aired_at <= today:
                episode_keys.add((season_number, episode_number))
    return episode_keys


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
            OwnedMedia.scope == SCOPE_MOVIE,
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


def _extract_radarr_search_command_id(radarr_movie: dict) -> int | None:
    """Extract Scenario's tracked Radarr search command ID from a movie response."""
    return _safe_int(radarr_movie.get("_scenario_search_command_id"))


def _extract_sonarr_series_id(sonarr_series: dict) -> int | None:
    """Extract the Sonarr internal series ID from an add/search response."""
    return _safe_int(sonarr_series.get("id"))


def _mark_request_failed(
    database_session: Session,
    download_request: DownloadRequest,
    error_message: str,
) -> None:
    """Mark a download request as failed and persist the error."""
    download_request.status = DOWNLOAD_STATUS_FAILED
    download_request.error_message = error_message[:500]
    database_session.commit()
