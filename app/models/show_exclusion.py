"""Account-owned release-feed exclusions, independent of views and progress."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ShowExclusion(Base):
    """Keep display snapshots so excluded shows remain restorable without TMDB."""

    __tablename__ = "show_exclusion"
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_model.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    poster_path: Mapped[str] = mapped_column(String(500), nullable=False)
    __table_args__ = (CheckConstraint("tmdb_id > 0", name="ck_show_exclusion_tmdb"),)
