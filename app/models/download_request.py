"""Download request model for Radarr/Sonarr media requests."""

import uuid

from sqlalchemy import ARRAY, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class DownloadRequest(Base):
    """Media download request tracked locally by Scenario."""

    __tablename__ = "download_request_model"
    __table_args__ = (
        Index(
            "idx_download_request_tmdb_type_source",
            "tmdb_id",
            "media_type",
            "source",
        ),
        Index("idx_download_request_status", "status"),
        Index("idx_download_request_user", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_model.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tmdb_id = Column(Integer, nullable=False)
    media_type = Column(String(50), nullable=False)
    source = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    radarr_movie_id = Column(Integer, nullable=True)
    genre_ids = Column(ARRAY(Integer), default=[0], nullable=False)
    poster_path = Column(String, nullable=False, default="")
    backdrop_path = Column(String, nullable=False, default="")
    release_date = Column(String, nullable=False, default="")
    release_year = Column(String, nullable=False, default="")
    runtime = Column(Integer, nullable=False, default=0)
    title = Column(String, nullable=False, default="")
    error_message = Column(String, nullable=True)
    download_title = Column(String, nullable=True)
    download_client = Column(String, nullable=True)
    quality = Column(String, nullable=True)
    size = Column(Integer, nullable=True)
    size_left = Column(Integer, nullable=True)
    time_left = Column(String, nullable=True)
    tracked_download_status = Column(String, nullable=True)
    tracked_download_state = Column(String, nullable=True)
    requested_at = Column(DateTime, nullable=False)

    requester = relationship("User")

    def __str__(self):
        """Return user-friendly string representation."""
        return (
            f"DownloadRequest(tmdb_id='{self.tmdb_id}', type='{self.media_type}', "
            f"status='{self.status}')"
        )
