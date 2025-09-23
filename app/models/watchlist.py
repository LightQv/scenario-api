"""
Watchlist model for organizing media collections.

This module defines the Watchlist SQLAlchemy model which allows users
to create and organize collections of movies and TV shows they want to watch.
"""

from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.database.base import Base


class Watchlist(Base):
    """
    Watchlist model for organizing user's media collections.

    This model represents user-created collections of movies and TV shows.
    Users can create multiple watchlists to organize their content by themes,
    genres, or any other criteria. Each watchlist belongs to a single user
    and can contain multiple media items.

    Attributes:
        id (UUID): Primary key - unique identifier for the watchlist
        title (str): User-defined name/title for the watchlist
        author_id (UUID): Foreign key reference to the User who created this watchlist

    Relationships:
        author: Many-to-one relationship with User model (watchlist owner)
        medias: One-to-many relationship with Media model (contained media items)

    Example:
        >>> watchlist = Watchlist(
        ...     title="Action Movies to Watch",
        ...     author_id=user.id
        ... )
        >>> db.session.add(watchlist)
        >>> db.session.commit()

    Note:
        When a watchlist is deleted, all associated media items are also deleted
        due to the cascade configuration. When a user is deleted, their watchlists
        are automatically deleted as well.
    """

    __tablename__ = "watchlist_model"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    author_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_model.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    author = relationship("User", back_populates="watchlists")
    medias = relationship(
        "Media",
        back_populates="watchlist",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __str__(self):
        """Return user-friendly string representation."""
        return f"Watchlist(title='{self.title}', author_id='{self.author_id}')"
