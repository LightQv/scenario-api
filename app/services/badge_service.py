"""Profile badge progress and unlock service."""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import DownloadRequest, Media, OwnedMedia, UserBadge, View, Watchlist
from app.schemas import BadgeListResponse, BadgeResponse


MOVIE_MEDIA_TYPE = "movie"
TV_MEDIA_TYPE = "tv"
USER_WATCHLIST_TYPE = "USER"
MOVIE_ACTION_GENRE_ID = 28
MOVIE_ADVENTURE_GENRE_ID = 12
MOVIE_ANIMATION_GENRE_ID = 16
MOVIE_COMEDY_GENRE_ID = 35
MOVIE_CRIME_GENRE_ID = 80
MOVIE_DRAMA_GENRE_ID = 18
MOVIE_FANTASY_GENRE_ID = 14
MOVIE_HORROR_GENRE_ID = 27
MOVIE_MYSTERY_GENRE_ID = 9648
MOVIE_ROMANCE_GENRE_ID = 10749
MOVIE_SCI_FI_GENRE_ID = 878
MOVIE_THRILLER_GENRE_ID = 53
TV_ACTION_ADVENTURE_GENRE_ID = 10759
TV_ANIMATION_GENRE_ID = 16
TV_COMEDY_GENRE_ID = 35
TV_CRIME_GENRE_ID = 80
TV_DRAMA_GENRE_ID = 18
TV_MYSTERY_GENRE_ID = 9648
TV_SCI_FI_FANTASY_GENRE_ID = 10765
LONG_MOVIE_MINUTES = 180
SUPPORTED_GENRE_IDS = {
    MOVIE_ACTION_GENRE_ID,
    MOVIE_ADVENTURE_GENRE_ID,
    MOVIE_ANIMATION_GENRE_ID,
    MOVIE_COMEDY_GENRE_ID,
    MOVIE_CRIME_GENRE_ID,
    MOVIE_DRAMA_GENRE_ID,
    MOVIE_FANTASY_GENRE_ID,
    MOVIE_HORROR_GENRE_ID,
    MOVIE_MYSTERY_GENRE_ID,
    MOVIE_ROMANCE_GENRE_ID,
    MOVIE_SCI_FI_GENRE_ID,
    MOVIE_THRILLER_GENRE_ID,
    TV_ACTION_ADVENTURE_GENRE_ID,
    TV_SCI_FI_FANTASY_GENRE_ID,
}


@dataclass(frozen=True)
class BadgeDefinition:
    """Static badge definition used to compute progress for one metric."""

    id: str
    title: str
    description: str
    metric: str
    target: int
    icon: str
    tier: str


BADGE_DEFINITIONS: tuple[BadgeDefinition, ...] = (
    BadgeDefinition("movie_count_i", "First Scene", "Watch 25 movies", "movies_watched", 25, "film", "bronze"),
    BadgeDefinition("movie_count_ii", "Movie Night", "Watch 100 movies", "movies_watched", 100, "ticket", "silver"),
    BadgeDefinition("movie_count_iii", "Cinephile", "Watch 500 movies", "movies_watched", 500, "star", "gold"),
    BadgeDefinition("movie_count_iv", "\"I'll Be Back\"", "Watch 1000 movies", "movies_watched", 1000, "videocam", "platinum"),
    BadgeDefinition("tv_show_count_i", "Pilot Episode", "Watch 25 TV shows", "tv_shows_watched", 25, "tv", "bronze"),
    BadgeDefinition("tv_show_count_ii", "Binge Starter", "Watch 100 TV shows", "tv_shows_watched", 100, "play-forward", "silver"),
    BadgeDefinition("tv_show_count_iii", "Seasoned", "Watch 500 TV shows", "tv_shows_watched", 500, "albums", "gold"),
    BadgeDefinition("tv_show_count_iv", "\"Winter Is Coming\"", "Watch 1000 TV shows", "tv_shows_watched", 1000, "easel", "platinum"),
    BadgeDefinition("movie_collection_i", "Archivist I", "Add 10 movies to your collection", "available_movies", 10, "archive", "bronze"),
    BadgeDefinition("movie_collection_ii", "Archivist II", "Add 50 movies to your collection", "available_movies", 50, "library", "silver"),
    BadgeDefinition("movie_collection_iii", "Archivist III", "Add 150 movies to your collection", "available_movies", 150, "trophy", "gold"),
    BadgeDefinition("movie_collection_iv", "\"This Belongs in a Museum!\"", "Add 300 movies to your collection", "available_movies", 300, "diamond", "platinum"),
    BadgeDefinition("download_request_i", "First Request", "Request 5 downloads", "download_requests", 5, "cloud-download", "bronze"),
    BadgeDefinition("download_request_ii", "Queue Master", "Request 25 downloads", "download_requests", 25, "rocket", "silver"),
    BadgeDefinition("download_request_iii", "Signal Boost", "Request 100 downloads", "download_requests", 100, "radio", "gold"),
    BadgeDefinition("download_request_iv", "\"Guns. Lots of Guns.\"", "Request 250 downloads", "download_requests", 250, "code-download", "platinum"),
    BadgeDefinition("watchlist_created_i", "Curator", "Create 1 personal watchlist", "watchlists_created", 1, "folder-open", "bronze"),
    BadgeDefinition("watchlist_created_ii", "Shelf Builder", "Create 5 personal watchlists", "watchlists_created", 5, "file-tray-stacked", "silver"),
    BadgeDefinition("watchlist_created_iii", "Collection Architect", "Create 10 personal watchlists", "watchlists_created", 10, "albums", "gold"),
    BadgeDefinition("watchlist_created_iv", "Library of Babel", "Create 20 personal watchlists", "watchlists_created", 20, "library", "platinum"),
    BadgeDefinition("watchlist_media_i", "Collector's Eye", "Save 25 media to watchlists", "watchlist_items", 25, "bookmark", "bronze"),
    BadgeDefinition("watchlist_media_ii", "Shelf Space", "Save 100 media to watchlists", "watchlist_items", 100, "bookmarks", "silver"),
    BadgeDefinition("watchlist_media_iii", "Vault Keeper", "Save 250 media to watchlists", "watchlist_items", 250, "file-tray-full", "gold"),
    BadgeDefinition("watchlist_media_iv", "The Infinite Queue", "Save 500 media to watchlists", "watchlist_items", 500, "infinite", "platinum"),
    BadgeDefinition("genre_breadth_i", "The Multiverse", f"Watch media from all {len(SUPPORTED_GENRE_IDS)} supported genres", "viewed_genres", len(SUPPORTED_GENRE_IDS), "prism", "platinum"),
    BadgeDefinition("action_adventure_i", "Action Hero", "Watch 25 action or adventure media", "action_items", 25, "flash", "bronze"),
    BadgeDefinition("action_adventure_ii", "Explosive Taste", "Watch 75 action or adventure media", "action_items", 75, "flame", "silver"),
    BadgeDefinition("action_adventure_iii", "Adrenaline Junkie", "Watch 150 action or adventure media", "action_items", 150, "speedometer", "gold"),
    BadgeDefinition("action_adventure_iv", "\"Yippee-Ki-Yay\"", "Watch 300 action or adventure media", "action_items", 300, "rocket", "platinum"),
    BadgeDefinition("horror_i", "Horror Hour", "Watch 25 horror media", "horror_items", 25, "skull", "bronze"),
    BadgeDefinition("horror_ii", "Night Watcher", "Watch 75 horror media", "horror_items", 75, "moon", "silver"),
    BadgeDefinition("horror_iii", "Fear Collector", "Watch 150 horror media", "horror_items", 150, "eye", "gold"),
    BadgeDefinition("horror_iv", "\"What's your favorite scary movie?\"", "Watch 300 horror media", "horror_items", 300, "warning", "platinum"),
    BadgeDefinition("comedy_i", "Laugh Track", "Watch 25 comedy media", "comedy_items", 25, "happy", "bronze"),
    BadgeDefinition("comedy_ii", "Comedy Regular", "Watch 75 comedy media", "comedy_items", 75, "chatbubble", "silver"),
    BadgeDefinition("comedy_iii", "Punchline Pro", "Watch 150 comedy media", "comedy_items", 150, "mic", "gold"),
    BadgeDefinition("comedy_iv", "\"Why So Serious?\"", "Watch 300 comedy media", "comedy_items", 300, "sparkles", "platinum"),
    BadgeDefinition("sci_fi_fantasy_i", "Mind Bender", "Watch 25 sci-fi or fantasy media", "sci_fi_fantasy_items", 25, "planet", "bronze"),
    BadgeDefinition("sci_fi_fantasy_ii", "Beyond the Stars", "Watch 75 sci-fi or fantasy media", "sci_fi_fantasy_items", 75, "telescope", "silver"),
    BadgeDefinition("sci_fi_fantasy_iii", "Future Shock", "Watch 150 sci-fi or fantasy media", "sci_fi_fantasy_items", 150, "aperture", "gold"),
    BadgeDefinition("sci_fi_fantasy_iv", "\"May the Force Be With You\"", "Watch 300 sci-fi or fantasy media", "sci_fi_fantasy_items", 300, "planet", "platinum"),
    BadgeDefinition("crime_thriller_mystery_i", "Crime Board", "Watch 25 crime, thriller, or mystery media", "crime_thriller_mystery_items", 25, "finger-print", "bronze"),
    BadgeDefinition("crime_thriller_mystery_ii", "Case File", "Watch 75 crime, thriller, or mystery media", "crime_thriller_mystery_items", 75, "document-text", "silver"),
    BadgeDefinition("crime_thriller_mystery_iii", "Master Detective", "Watch 150 crime, thriller, or mystery media", "crime_thriller_mystery_items", 150, "search", "gold"),
    BadgeDefinition("crime_thriller_mystery_iv", "\"I See Dead People\"", "Watch 300 crime, thriller, or mystery media", "crime_thriller_mystery_items", 300, "eye", "platinum"),
    BadgeDefinition("romance_i", "Meet Cute", "Watch 25 romance media", "romance_items", 25, "heart", "bronze"),
    BadgeDefinition("romance_ii", "Hopeless Romantic", "Watch 75 romance media", "romance_items", 75, "rose", "silver"),
    BadgeDefinition("romance_iii", "Grand Gesture", "Watch 150 romance media", "romance_items", 150, "gift", "gold"),
    BadgeDefinition("romance_iv", "\"To Me, You Are Perfect\"", "Watch 300 romance media", "romance_items", 300, "heart-circle", "platinum"),
    BadgeDefinition("drama_i", "Dramatic Pause", "Watch 25 drama media", "drama_items", 25, "pause", "bronze"),
    BadgeDefinition("drama_ii", "Emotional Range", "Watch 75 drama media", "drama_items", 75, "pulse", "silver"),
    BadgeDefinition("drama_iii", "Tearjerker", "Watch 150 drama media", "drama_items", 150, "water", "gold"),
    BadgeDefinition("drama_iv", "\"I'm the King of the World!\"", "Watch 300 drama media", "drama_items", 300, "boat", "platinum"),
    BadgeDefinition("animation_i", "Frame by Frame", "Watch 25 animation media", "animation_items", 25, "images", "bronze"),
    BadgeDefinition("animation_ii", "Saturday Morning", "Watch 75 animation media", "animation_items", 75, "sunny", "silver"),
    BadgeDefinition("animation_iii", "Animated Soul", "Watch 150 animation media", "animation_items", 150, "color-wand", "gold"),
    BadgeDefinition("animation_iv", "\"To Infinity and Beyond\"", "Watch 300 animation media", "animation_items", 300, "infinite", "platinum"),
    BadgeDefinition("long_movie_i", "The Long Cut", "Watch a movie over 3 hours", "long_movies", 1, "hourglass", "platinum"),
    BadgeDefinition("classic_movie_i", "Time Machine", "Watch a movie released before 1980", "classic_movies", 1, "time", "platinum"),
    BadgeDefinition("double_feature_i", "Double Feature", "Watch 2 movies on the same day", "double_feature_days", 1, "film", "platinum"),
    BadgeDefinition("mixed_night_i", "The Crossover", "Watch a movie and a TV show on the same day", "mixed_media_days", 1, "shuffle", "platinum"),
    BadgeDefinition("season_hunter_i", "Season Hunter", "Request a season download", "season_download_requests", 1, "albums", "platinum"),
    BadgeDefinition("watchtime_i", "Just One More", "Log 100 hours watched", "watch_hours", 100, "time", "bronze"),
    BadgeDefinition("watchtime_ii", "Lost Weekend", "Log 500 hours watched", "watch_hours", 500, "calendar", "silver"),
    BadgeDefinition("watchtime_iii", "Time Well Spent", "Log 1500 hours watched", "watch_hours", 1500, "hourglass", "gold"),
    BadgeDefinition("watchtime_iv", "\"We Are the Walking Dead\"", "Log 3000 hours watched", "watch_hours", 3000, "walk", "platinum"),
)


def get_user_badges(database_session: Session, user_id: UUID) -> BadgeListResponse:
    """Return badge progress for one user and persist newly unlocked badges.

    Args:
        database_session: Active SQLAlchemy session.
        user_id: Authenticated user identifier.

    Returns:
        BadgeListResponse: All badge definitions with progress and unlock state.
    """
    metrics = _collect_badge_metrics(database_session, user_id)
    unlocked_by_id = _get_unlocked_badges(database_session, user_id)
    now = datetime.utcnow()
    new_unlocks: list[dict[str, object]] = []

    for badge in BADGE_DEFINITIONS:
        current = metrics.get(badge.metric, 0)
        if current >= badge.target and badge.id not in unlocked_by_id:
            new_unlocks.append(
                {
                    "id": uuid4(),
                    "user_id": user_id,
                    "badge_id": badge.id,
                    "unlocked_at": now,
                }
            )

    if new_unlocks:
        statement = insert(UserBadge).values(new_unlocks)
        statement = statement.on_conflict_do_nothing(index_elements=["user_id", "badge_id"])
        database_session.execute(statement)
        database_session.commit()
        unlocked_by_id = _get_unlocked_badges(database_session, user_id)

    responses = [
        _build_badge_response(badge, metrics.get(badge.metric, 0), unlocked_by_id.get(badge.id))
        for badge in BADGE_DEFINITIONS
    ]
    return BadgeListResponse(badges=responses)


def _collect_badge_metrics(database_session: Session, user_id: UUID) -> dict[str, int]:
    """Collect all badge metrics from existing user-owned tables."""
    movies_watched = _count_views(database_session, user_id, MOVIE_MEDIA_TYPE)
    tv_shows_watched = _count_views(database_session, user_id, TV_MEDIA_TYPE)
    available_movies = _count_owned_movies(database_session, user_id)
    download_requests = _count_download_requests(database_session, user_id)
    watchlists_created = _count_user_watchlists(database_session, user_id)
    watchlist_items = _count_watchlist_items(database_session, user_id)
    viewed_genres = _count_viewed_genres(database_session, user_id)
    watch_hours = _count_watch_hours(database_session, user_id)
    action_items = _count_views_with_genres(
        database_session,
        user_id,
        {
            MOVIE_ACTION_GENRE_ID,
            MOVIE_ADVENTURE_GENRE_ID,
            TV_ACTION_ADVENTURE_GENRE_ID,
        },
    )
    horror_items = _count_views_with_genres(database_session, user_id, {MOVIE_HORROR_GENRE_ID})
    comedy_items = _count_views_with_genres(
        database_session,
        user_id,
        {MOVIE_COMEDY_GENRE_ID, TV_COMEDY_GENRE_ID},
    )
    sci_fi_fantasy_items = _count_views_with_genres(
        database_session,
        user_id,
        {
            MOVIE_SCI_FI_GENRE_ID,
            MOVIE_FANTASY_GENRE_ID,
            TV_SCI_FI_FANTASY_GENRE_ID,
        },
    )
    crime_thriller_mystery_items = _count_views_with_genres(
        database_session,
        user_id,
        {
            MOVIE_CRIME_GENRE_ID,
            MOVIE_THRILLER_GENRE_ID,
            MOVIE_MYSTERY_GENRE_ID,
            TV_CRIME_GENRE_ID,
            TV_MYSTERY_GENRE_ID,
        },
    )
    romance_items = _count_views_with_genres(database_session, user_id, {MOVIE_ROMANCE_GENRE_ID})
    drama_items = _count_views_with_genres(
        database_session,
        user_id,
        {MOVIE_DRAMA_GENRE_ID, TV_DRAMA_GENRE_ID},
    )
    animation_items = _count_views_with_genres(
        database_session,
        user_id,
        {MOVIE_ANIMATION_GENRE_ID, TV_ANIMATION_GENRE_ID},
    )
    long_movies = _count_long_movies(database_session, user_id)
    classic_movies = _count_classic_movies(database_session, user_id)
    double_feature_days = _count_double_feature_days(database_session, user_id)
    mixed_media_days = _count_mixed_media_days(database_session, user_id)
    season_download_requests = _count_season_download_requests(database_session, user_id)

    return {
        "movies_watched": movies_watched,
        "tv_shows_watched": tv_shows_watched,
        "available_movies": available_movies,
        "download_requests": download_requests,
        "watchlists_created": watchlists_created,
        "watchlist_items": watchlist_items,
        "viewed_genres": viewed_genres,
        "watch_hours": watch_hours,
        "action_items": action_items,
        "horror_items": horror_items,
        "comedy_items": comedy_items,
        "sci_fi_fantasy_items": sci_fi_fantasy_items,
        "crime_thriller_mystery_items": crime_thriller_mystery_items,
        "romance_items": romance_items,
        "drama_items": drama_items,
        "animation_items": animation_items,
        "long_movies": long_movies,
        "classic_movies": classic_movies,
        "double_feature_days": double_feature_days,
        "mixed_media_days": mixed_media_days,
        "season_download_requests": season_download_requests,
    }


def _get_unlocked_badges(database_session: Session, user_id: UUID) -> dict[str, UserBadge]:
    """Return persisted badge unlocks keyed by badge ID."""
    user_badges = database_session.query(UserBadge).filter(UserBadge.user_id == user_id).all()
    return {user_badge.badge_id: user_badge for user_badge in user_badges}


def _build_badge_response(
    badge: BadgeDefinition,
    current: int,
    unlocked_badge: UserBadge | None,
) -> BadgeResponse:
    """Build one API badge response from static definition and progress."""
    return BadgeResponse(
        id=badge.id,
        title=badge.title,
        description=badge.description,
        current=max(0, current),
        target=badge.target,
        icon=badge.icon,
        tier=badge.tier,
        unlocked=unlocked_badge is not None,
        unlocked_at=unlocked_badge.unlocked_at if unlocked_badge else None,
    )


def _count_views(database_session: Session, user_id: UUID, media_type: str) -> int:
    """Count viewed rows for one media type."""
    return int(
        database_session.query(func.count(View.id))
        .filter(View.viewer_id == user_id, View.media_type == media_type)
        .scalar()
        or 0
    )


def _count_owned_movies(database_session: Session, user_id: UUID) -> int:
    """Count currently available movie rows."""
    return int(
        database_session.query(func.count(OwnedMedia.id))
        .filter(OwnedMedia.user_id == user_id, OwnedMedia.media_type == MOVIE_MEDIA_TYPE)
        .scalar()
        or 0
    )


def _count_download_requests(database_session: Session, user_id: UUID) -> int:
    """Count all download requests made by the user."""
    return int(
        database_session.query(func.count(DownloadRequest.id))
        .filter(DownloadRequest.user_id == user_id)
        .scalar()
        or 0
    )


def _count_user_watchlists(database_session: Session, user_id: UUID) -> int:
    """Count personal watchlists created by the user."""
    return int(
        database_session.query(func.count(Watchlist.id))
        .filter(Watchlist.author_id == user_id, Watchlist.type == USER_WATCHLIST_TYPE)
        .scalar()
        or 0
    )


def _count_watchlist_items(database_session: Session, user_id: UUID) -> int:
    """Count media items saved in the user's watchlists."""
    return int(
        database_session.query(func.count(Media.id))
        .join(Watchlist, Media.watchlist_id == Watchlist.id)
        .filter(Watchlist.author_id == user_id)
        .scalar()
        or 0
    )


def _count_viewed_genres(database_session: Session, user_id: UUID) -> int:
    """Count distinct non-placeholder genres across viewed media."""
    genre_ids: set[int] = set()
    rows = database_session.query(View.genre_ids).filter(View.viewer_id == user_id).all()
    for row in rows:
        for genre_id in row.genre_ids or []:
            if genre_id:
                genre_ids.add(int(genre_id))
    return len(genre_ids)


def _count_views_with_genres(database_session: Session, user_id: UUID, genre_ids: set[int]) -> int:
    """Count viewed rows that include at least one target genre."""
    count = 0
    rows = database_session.query(View.genre_ids).filter(View.viewer_id == user_id).all()
    for row in rows:
        if genre_ids.intersection(set(row.genre_ids or [])):
            count += 1
    return count


def _count_long_movies(database_session: Session, user_id: UUID) -> int:
    """Count viewed movies at or above the long-movie threshold."""
    return int(
        database_session.query(func.count(View.id))
        .filter(
            View.viewer_id == user_id,
            View.media_type == MOVIE_MEDIA_TYPE,
            View.runtime >= LONG_MOVIE_MINUTES,
        )
        .scalar()
        or 0
    )


def _count_classic_movies(database_session: Session, user_id: UUID) -> int:
    """Count viewed movies released before 1980."""
    return int(
        database_session.query(func.count(View.id))
        .filter(
            View.viewer_id == user_id,
            View.media_type == MOVIE_MEDIA_TYPE,
            View.release_date != "",
            View.release_date < "1980-01-01",
        )
        .scalar()
        or 0
    )


def _count_double_feature_days(database_session: Session, user_id: UUID) -> int:
    """Count days where the user watched at least two movies."""
    return int(
        database_session.query(func.count())
        .select_from(
            database_session.query(func.date(View.created_at).label("view_date"))
            .filter(View.viewer_id == user_id, View.media_type == MOVIE_MEDIA_TYPE)
            .group_by(func.date(View.created_at))
            .having(func.count(View.id) >= 2)
            .subquery()
        )
        .scalar()
        or 0
    )


def _count_mixed_media_days(database_session: Session, user_id: UUID) -> int:
    """Count days where the user watched both a movie and a TV show."""
    return int(
        database_session.query(func.count())
        .select_from(
            database_session.query(func.date(View.created_at).label("view_date"))
            .filter(
                View.viewer_id == user_id,
                View.media_type.in_([MOVIE_MEDIA_TYPE, TV_MEDIA_TYPE]),
            )
            .group_by(func.date(View.created_at))
            .having(func.count(func.distinct(View.media_type)) >= 2)
            .subquery()
        )
        .scalar()
        or 0
    )


def _count_season_download_requests(database_session: Session, user_id: UUID) -> int:
    """Count season-level download requests made by the user."""
    return int(
        database_session.query(func.count(DownloadRequest.id))
        .filter(
            DownloadRequest.user_id == user_id,
            DownloadRequest.scope == "season",
            DownloadRequest.season_number.isnot(None),
        )
        .scalar()
        or 0
    )


def _count_watch_hours(database_session: Session, user_id: UUID) -> int:
    """Count total watched runtime rounded down to hours."""
    total_minutes = int(
        database_session.query(func.coalesce(func.sum(View.runtime), 0))
        .filter(View.viewer_id == user_id)
        .scalar()
        or 0
    )
    return total_minutes // 60
