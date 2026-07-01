"""
Owned media model for tracking server-available movies and shows.

This module stores the normalized Scenario-side view of media already present
on the home server, as reported by integrations such as Radarr and Sonarr.
"""

import uuid

from sqlalchemy import ARRAY, Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base


class OwnedMedia(Base):
    """
    Owned media entry synced from a media-management source.

    Attributes:
        id: Primary key - unique identifier for this owned media row.
        tmdb_id: The Movie Database ID used by Scenario detail pages.
        media_type: Media type, currently ``movie`` for Radarr-owned movies.
        genre_ids: TMDB genre identifiers used by listing filters.
        poster_path: TMDB poster path.
        backdrop_path: TMDB backdrop path.
        release_date: TMDB release date.
        release_year: Release year used by listing sorts/statistics.
        runtime: Runtime in minutes.
        title: Display title.
        source: Integration source that reported the media, e.g. ``RADARR``.
        last_synced_at: Timestamp of the sync that last confirmed ownership.
        metadata_synced_at: Timestamp of the latest successful TMDB hydration.
    """

    __tablename__ = "owned_media_model"
    __table_args__ = (
        Index(
            "uq_owned_media_movie_tmdb_type_source",
            "user_id",
            "tmdb_id",
            "media_type",
            "source",
            unique=True,
            postgresql_where=text("scope = 'movie'"),
        ),
        Index(
            "uq_owned_media_episode_tmdb_type_source_season_episode",
            "user_id",
            "tmdb_id",
            "media_type",
            "source",
            "season_number",
            "episode_number",
            unique=True,
            postgresql_where=text("scope = 'episode'"),
        ),
        Index("idx_owned_media_user_tmdb_type", "user_id", "tmdb_id", "media_type"),
        Index("idx_owned_media_user_tmdb_type_source", "user_id", "tmdb_id", "media_type", "source"),
        Index("idx_owned_media_user_tv_episode", "user_id", "tmdb_id", "season_number", "episode_number"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_model.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tmdb_id = Column(Integer, nullable=False)
    media_type = Column(String(50), nullable=False)
    scope = Column(String(50), nullable=False, default="movie")
    tvdb_id = Column(Integer, nullable=True)
    sonarr_series_id = Column(Integer, nullable=True)
    season_number = Column(Integer, nullable=True)
    episode_number = Column(Integer, nullable=True)
    episode_title = Column(String, nullable=True)
    episode_air_date = Column(String, nullable=True)
    genre_ids = Column(ARRAY(Integer), default=[0], nullable=False)
    poster_path = Column(String, nullable=False, default="")
    backdrop_path = Column(String, nullable=False, default="")
    release_date = Column(String, nullable=False, default="")
    release_year = Column(String, nullable=False, default="")
    runtime = Column(Integer, nullable=False, default=0)
    title = Column(String, nullable=False, default="")
    source = Column(String(50), nullable=False)
    last_synced_at = Column(DateTime, nullable=False)
    metadata_synced_at = Column(DateTime, nullable=True)

    def __str__(self):
        """Return user-friendly string representation."""
        return (
            f"OwnedMedia(tmdb_id='{self.tmdb_id}', "
            f"type='{self.media_type}', scope='{self.scope}', source='{self.source}')"
        )
