"""Durable, owner-private desired states awaiting public catalogue validation."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Identity, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ProgressAction(Base):
    """Order overlapping show/season/episode actions without persisting client metadata."""

    __tablename__ = "progress_action"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_model.id", ondelete="CASCADE"), index=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    season_number: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    through: Mapped[date] = mapped_column(Date, nullable=False)
    watched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    record_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("sequence", name="uq_progress_action_sequence"),
        CheckConstraint("tmdb_id > 0", name="ck_progress_action_show"),
        CheckConstraint("season_number IS NULL OR season_number > 0", name="ck_progress_action_season"),
        CheckConstraint("episode_number IS NULL OR (season_number IS NOT NULL AND episode_number > 0)", name="ck_progress_action_episode"),
        CheckConstraint("status IN ('pending', 'applied', 'failed', 'cancelled')", name="ck_progress_action_status"),
    )
