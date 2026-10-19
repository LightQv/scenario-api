"""Shared public TMDB catalogues and durable, deduplicated refresh leases."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ReleaseCatalog(Base):
    """Keep the last complete catalogue available while its next refresh runs."""

    __tablename__ = "release_catalog"
    media_type: Mapped[str] = mapped_column(String(5), primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(String(5), primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_refresh_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("tmdb_id > 0", name="ck_release_catalog_tmdb"),
        CheckConstraint("media_type IN ('movie', 'tv')", name="ck_release_catalog_type"),
        CheckConstraint("language IN ('en-US', 'fr-FR')", name="ck_release_catalog_language"),
    )
