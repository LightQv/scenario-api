"""
Integration sync status model.

This table stores operational state for background/manual integration syncs
without mixing sync metadata into owned media availability rows.
"""

import uuid

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base


class IntegrationSyncStatus(Base):
    """
    Operational status for a media integration sync.

    Attributes:
        id: Primary key - unique identifier for this sync status row.
        source: Integration source, e.g. ``RADARR``.
        media_type: Media type synced by the source, e.g. ``movie``.
        status: Current or latest status: ``idle``, ``running``, ``success``, ``failed``.
        trigger: Last trigger type: ``manual`` or ``scheduled``.
        started_at: Timestamp when the latest sync started.
        finished_at: Timestamp when the latest sync finished.
        owned_count: Number of owned media rows stored by the latest successful sync.
        error_message: Latest sync failure message, if any.
    """

    __tablename__ = "integration_sync_status"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "media_type",
            name="uq_integration_sync_status_source_media_type",
        ),
        Index("idx_integration_sync_status_source_media_type", "source", "media_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(50), nullable=False)
    media_type = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="idle")
    trigger = Column(String(50), nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    owned_count = Column(Integer, nullable=True)
    error_message = Column(String(500), nullable=True)

    def __str__(self):
        """Return user-friendly string representation."""
        return (
            f"IntegrationSyncStatus(source='{self.source}', "
            f"type='{self.media_type}', status='{self.status}')"
        )
