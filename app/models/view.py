"""
View model for tracking user viewing history.

This module defines the View SQLAlchemy model which records when users
have watched movies or TV shows, enabling viewing history and statistics.
"""

from sqlalchemy import Column, String, Integer, ForeignKey, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.database.base import Base


class View(Base):
    """
    View model for tracking user viewing history and statistics.

    This model records when a user has watched a movie or TV show episode.
    It stores the same media information as the Media model but serves a different
    purpose - tracking what has been watched rather than what someone wants to watch.
    This enables viewing statistics, recommendations, and history tracking.

    Attributes:
        id (UUID): Primary key - unique identifier for this viewing record
        tmdb_id (int): The Movie Database ID for external reference
        genre_ids (List[int]): Array of TMDB genre IDs for statistics
        poster_path (str): URL path to the movie/show poster image
        backdrop_path (str): URL path to the backdrop/banner image
        release_date (str): Full release date in string format (YYYY-MM-DD)
        release_year (str): Year of release for statistical grouping
        runtime (int): Duration in minutes for time tracking statistics
        title (str): Movie or TV show title
        media_type (str): Type of media ('movie' or 'tv')
        viewer_id (UUID): Foreign key reference to the User who watched this

    Relationships:
        viewer: Many-to-one relationship with User model

    Example:
        >>> view = View(
        ...     tmdb_id=550,
        ...     title="Fight Club",
        ...     media_type="movie",
        ...     runtime=139,
        ...     release_date="1999-10-15",
        ...     release_year="1999",
        ...     genre_ids=[18, 53],
        ...     poster_path="/bptfVGEQuv6vDTIMVCHjJ9Dz8PX.jpg",
        ...     backdrop_path="/52AfXWuXCHn3UjD17rBruA9f5qb.jpg",
        ...     viewer_id=user.id
        ... )
        >>> db.session.add(view)
        >>> db.session.commit()

    Note:
        When a user is deleted, all their viewing records are automatically
        deleted due to the CASCADE foreign key constraint.
    """

    __tablename__ = "view_model"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tmdb_id = Column(Integer, nullable=False, index=True)
    genre_ids = Column(ARRAY(Integer), default=[0])
    poster_path = Column(String, nullable=False)
    backdrop_path = Column(String, nullable=False)
    release_date = Column(String, nullable=False)
    release_year = Column(String, nullable=False, index=True)
    runtime = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    media_type = Column(String, nullable=False, index=True)
    viewer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_model.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    viewer = relationship("User", back_populates="views")

    def __str__(self):
        """Return user-friendly string representation."""
        return f"View(title='{self.title}', type='{self.media_type}', year='{self.release_year}')"
