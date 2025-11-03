"""
Watchlist type enumeration.

Defines the types of watchlists that can exist in the system.
"""

import enum


class WatchlistType(str, enum.Enum):
    """
    Enumeration for watchlist types.

    Attributes:
        USER: User-created watchlist that can be modified and deleted
        SYSTEM: System-generated watchlist that cannot be modified or deleted
    """
    USER = "USER"
    SYSTEM = "SYSTEM"
