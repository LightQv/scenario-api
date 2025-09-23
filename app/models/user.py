"""
User model for authentication and profile management.

This module defines the User SQLAlchemy model which handles user accounts,
authentication, and profile information in the Scenario API.
"""

from sqlalchemy import Column, String
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.database.base import Base


class User(Base):
    """
    User model for storing user account and profile information.

    This model represents registered users in the Scenario API application.
    It handles user authentication, profile data, and serves as the parent
    for user-related data like watchlists and viewing history.

    Attributes:
        id (UUID): Primary key - unique identifier for the user
        username (str): Unique username for display and identification
        email (str): Unique email address for authentication and notifications
        hashed_password (str): Bcrypt hashed password for secure authentication
        password_token (str, optional): Token for password reset functionality
        profile_banner (str, optional): URL to user's profile banner image

    Relationships:
        watchlists: One-to-many relationship with Watchlist model
        views: One-to-many relationship with View model (viewing history)

    Example:
        >>> user = User(
        ...     username="moviefan123",
        ...     email="fan@example.com",
        ...     hashed_password="$2b$12$..."
        ... )
        >>> db.session.add(user)
        >>> db.session.commit()
    """

    __tablename__ = "user_model"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    password_token = Column(String, nullable=True)
    profile_banner = Column(String, nullable=True)

    # Relationships with cascading deletes
    watchlists = relationship(
        "Watchlist",
        back_populates="author",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    views = relationship(
        "View", back_populates="viewer", cascade="all, delete-orphan", lazy="dynamic"
    )

    def __str__(self):
        """Return user-friendly string representation."""
        return f"User(username='{self.username}', email='{self.email}')"
