"""Private episode progress, independent of historical show statistics."""

from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, ForeignKeyConstraint, Integer, true
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ShowProgress(Base):
    """Freeze the released-episode assumption when a show is marked watched."""

    __tablename__ = "show_progress"
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_model.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    caught_up_through: Mapped[date] = mapped_column(Date, nullable=False)
    __table_args__ = (CheckConstraint("tmdb_id > 0", name="ck_show_progress_tmdb"),)


class EpisodeProgress(Base):
    """Store explicitly watched regular episodes without creating history rows."""

    __tablename__ = "episode_progress"
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_model.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    watched: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tmdb_id"],
            ["show_progress.user_id", "show_progress.tmdb_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("tmdb_id > 0", name="ck_episode_progress_tmdb"),
        CheckConstraint("season_number > 0", name="ck_episode_progress_season"),
        CheckConstraint("episode_number > 0", name="ck_episode_progress_episode"),
    )
