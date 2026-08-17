"""User-owned long-term API tokens."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class UserApiToken(Base):
    """Long-term bearer token tied to one Scenario user account."""

    __tablename__ = "user_api_token_model"
    __table_args__ = (
        Index("idx_user_api_token_user_id", "user_id"),
        Index("idx_user_api_token_hash", "token_hash", unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_model.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    token_hash = Column(String(128), nullable=False)
    encrypted_token = Column(String, nullable=False)
    scopes = Column(JSON, nullable=False, default=list)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User")

    def __str__(self):
        """Return user-friendly string representation."""
        return f"UserApiToken(user_id='{self.user_id}', name='{self.name}')"
