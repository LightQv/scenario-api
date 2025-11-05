"""
Media type enumeration.

Defines the types of media states in the system.
"""

import enum


class MediaType(str, enum.Enum):
    """
    Enumeration for media types/states.

    Attributes:
        PENDING: Media that is bookmarked/pending to be added to a watchlist
        IN_WATCHLIST: Media that is already in a user's watchlist
    """
    PENDING = "PENDING"
    IN_WATCHLIST = "IN_WATCHLIST"
