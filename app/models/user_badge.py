"""Persistent user badge unlock model."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base


class UserBadge(Base):
    """A badge permanently unlocked by one user."""

    __tablename__ = "user_badge_model"
    __table_args__ = (
        UniqueConstraint("user_id", "badge_id", name="uq_user_badge_user_badge_id"),
        Index("idx_user_badge_user_id", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_model.id", ondelete="CASCADE"),
        nullable=False,
    )
    badge_id = Column(String(100), nullable=False)
    unlocked_at = Column(DateTime, nullable=False)

    def __str__(self):
        """Return user-friendly string representation."""
        return f"UserBadge(user_id='{self.user_id}', badge_id='{self.badge_id}')"
