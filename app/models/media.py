"""
Media model for storing movie and TV show information.

This module defines the Media SQLAlchemy model which stores information
about movies and TV shows that users add to their watchlists.
"""

from sqlalchemy import Column, String, Integer, ForeignKey, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.database.base import Base


class Media(Base):
    """
    Media model for storing movie and TV show information in watchlists.

    This model represents individual movies or TV shows that users add to their
    watchlists. It stores metadata from TMDB (The Movie Database) including
    titles, posters, release dates, and genre information.

    Attributes:
        id (UUID): Primary key - unique identifier for this media entry
        tmdb_id (int): The Movie Database ID for external reference
        genre_ids (List[int]): Array of TMDB genre IDs for categorization
        poster_path (str): URL path to the movie/show poster image
        backdrop_path (str): URL path to the backdrop/banner image
        release_date (str): Release date in string format (YYYY-MM-DD)
        runtime (int): Duration in minutes
        title (str): Movie or TV show title
        media_type (str): Type of media ('movie' or 'tv')
        watchlist_id (UUID): Foreign key reference to the containing Watchlist

    Relationships:
        watchlist: Many-to-one relationship with Watchlist model

    Example:
        >>> media = Media(
        ...     tmdb_id=550,
        ...     title="Fight Club",
        ...     media_type="movie",
        ...     runtime=139,
        ...     release_date="1999-10-15",
        ...     genre_ids=[18, 53],
        ...     poster_path="/bptfVGEQuv6vDTIMVCHjJ9Dz8PX.jpg",
        ...     backdrop_path="/52AfXWuXCHn3UjD17rBruA9f5qb.jpg",
        ...     watchlist_id=watchlist.id
        ... )
        >>> db.session.add(media)
        >>> db.session.commit()

    Note:
        When a watchlist is deleted, all associated media items are automatically
        deleted due to the CASCADE foreign key constraint.
    """

    __tablename__ = "media_model"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tmdb_id = Column(Integer, nullable=False, index=True)
    genre_ids = Column(ARRAY(Integer), default=[0])
    poster_path = Column(String, nullable=False)
    backdrop_path = Column(String, nullable=False)
    release_date = Column(String, nullable=False)
    runtime = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    media_type = Column(String, nullable=False, index=True)
    watchlist_id = Column(
        UUID(as_uuid=True),
        ForeignKey("watchlist_model.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    watchlist = relationship("Watchlist", back_populates="medias")

    def __str__(self):
        """Return user-friendly string representation."""
        return f"Media(title='{self.title}', type='{self.media_type}', tmdb_id={self.tmdb_id})"
