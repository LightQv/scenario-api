"""
Owned media service.

This module reconciles integration data into Scenario's normalized owned media
table and provides cheap DB-backed availability checks for the mobile app.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import OwnedMedia
from app.schemas import (
    OwnedMediaResponse,
    OwnedMediaStatusResponse,
    OwnedMediaSyncResponse,
)
from app.services.radarr_service import RadarrService

RADARR_SOURCE = "RADARR"
MOVIE_MEDIA_TYPE = "movie"


def sync_radarr_owned_movies(database_session: Session) -> OwnedMediaSyncResponse:
    """
    Sync Radarr-owned movies into the owned media table.

    The sync stores only movies that Radarr reports as having an imported file.
    Current Radarr/movie rows are replaced atomically with the latest Radarr
    snapshot to remove stale ownership rows.

    Args:
        database_session: Database session dependency.

    Returns:
        OwnedMediaSyncResponse: Summary of the sync result.
    """
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
    database_session.commit()

    return OwnedMediaSyncResponse(
        source=RADARR_SOURCE,
        media_type=MOVIE_MEDIA_TYPE,
        owned_count=len(tmdb_ids),
        synced_at=synced_at,
    )


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
