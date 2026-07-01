"""Per-user Radarr/Sonarr integration settings."""

import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class UserIntegrationSettings(Base):
    """User-owned download integration configuration."""

    __tablename__ = "user_integration_settings_model"
    __table_args__ = (
        UniqueConstraint("user_id", "source", name="uq_user_integration_settings_user_source"),
        Index("idx_user_integration_settings_user", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_model.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source = Column(String(50), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    config = Column(JSON, nullable=False, default=dict)
    encrypted_secrets = Column(JSON, nullable=False, default=dict)

    user = relationship("User")

    def __str__(self):
        """Return user-friendly string representation."""
        return f"UserIntegrationSettings(user_id='{self.user_id}', source='{self.source}')"
