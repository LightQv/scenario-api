"""Read owner-scoped viewing intentions without rewriting historical records."""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EpisodeProgress, Media, ShowProgress, View, Watchlist


@dataclass
class OwnerActivity:
    """Private sources shared by Next, Viewed and release notifications."""

    cutoffs: dict[int, date]
    overrides: dict[int, dict[tuple[int, int], bool]]
    bookmarks: set[tuple[str, int]]
    history: set[tuple[str, int]]

    def tv_ids(self) -> set[int]:
        """Return candidates, excluding empty/false-only tracking baselines."""
        return {
            number for number, cutoff in self.cutoffs.items()
            if cutoff != date.min or any(self.overrides.get(number, {}).values())
        } | {number for kind, number in self.bookmarks | self.history if kind == "tv"}

    def follows_tv(self, number: int, watched_count: int) -> bool:
        """An empty tracking row is not an independent viewing intention."""
        return watched_count > 0 or ("tv", number) in self.bookmarks or ("tv", number) in self.history


def owner_activity(db: Session, owner: UUID) -> OwnerActivity:
    """Batch-read cookie-owner sources; never create views, dates or progress.

    Args:
        db: Request-scoped database session.
        owner: Authenticated account identity.

    Returns:
        Private intentions and historical watched assumptions for this owner only.
    """
    cutoffs: dict[int, date] = {
        row.tmdb_id: row.caught_up_through for row in db.scalars(
            select(ShowProgress).where(ShowProgress.user_id == owner)
        ).all()
    }
    overrides: dict[int, dict[tuple[int, int], bool]] = {}
    for row in db.scalars(select(EpisodeProgress).where(EpisodeProgress.user_id == owner)).all():
        overrides.setdefault(row.tmdb_id, {})[(row.season_number, row.episode_number)] = row.watched
    bookmarks: set[tuple[str, int]] = {
        (row.media_type, row.tmdb_id) for row in db.scalars(
            select(Media).join(Watchlist, Media.watchlist_id == Watchlist.id).where(
                Watchlist.author_id == owner, Watchlist.type == "SYSTEM", Media.type == "PENDING",
                Media.media_type.in_(("movie", "tv")),
            )
        ).all()
    }
    history: set[tuple[str, int]] = {
        (row.media_type, row.tmdb_id) for row in db.scalars(
            select(View).where(View.viewer_id == owner, View.media_type.in_(("movie", "tv")))
        ).all()
    }
    return OwnerActivity(cutoffs, overrides, bookmarks, history)


def watched_regular_count(payload: dict[str, Any], cutoff: date,
                          overrides: dict[tuple[int, int], bool], day: date) -> int:
    """Count known released watched episodes, honoring negative overrides.

    This uses the same compact catalogue as Next, without upstream requests.
    Unknown/future dates and specials cannot establish viewing activity.
    """
    watched: set[tuple[int, int]] = set()
    for season in payload.get("seasons", []):
        number: Any = season.get("season_number")
        if type(number) is not int or number <= 0:
            continue
        for episode in payload.get(f"season/{number}", {}).get("episodes", []):
            ep: Any = episode.get("episode_number")
            try:
                aired: date = date.fromisoformat(episode.get("air_date") or "")
            except (ValueError, TypeError):
                continue
            if type(ep) is int and ep > 0 and aired <= day and overrides.get((number, ep), aired <= cutoff):
                watched.add((number, ep))
    return len(watched)
