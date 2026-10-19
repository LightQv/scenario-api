"""Combine owner-scoped progress with cached public TMDB release metadata."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from functools import partial
from threading import Lock
from time import monotonic
from typing import Any, TypeAlias
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import EpisodeProgress, Media, ShowExclusion, ShowProgress, Watchlist
from app.schemas.up_next import (
    ExcludedShow, EpisodeRef, EpisodeWatched, NextEntry, NextFeed,
    ShowExclusionRequest, ShowProgressState, WatchedEpisodeState,
)
from app.services.tmdb_service import TmdbService

# Only public metadata is cached. Private feeds/progress never enter this cache.
_metadata: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_cache_lock: Lock = Lock()
_workers: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=6)
TitleSource: TypeAlias = tuple[str, int, date | None, frozenset[tuple[int, int]]]
TitleResult: TypeAlias = tuple[NextEntry | None, NextEntry | None, NextEntry | None]


def utc_today() -> date:
    """Return the date used consistently for release and baseline comparisons."""
    return datetime.now(timezone.utc).date()


def metadata(path: str, language: str) -> dict[str, Any]:
    """Fetch bounded, hour-cached public metadata, never caching failed requests."""
    key: tuple[str, str] = (path, language)
    with _cache_lock:
        cached = _metadata.get(key)
        if cached and cached[0] > monotonic():
            return cached[1]
    result: dict[str, Any] = TmdbService().get_release_details(path, language)
    if not isinstance(result, dict):
        raise RuntimeError("Invalid TMDB release details")
    with _cache_lock:
        if len(_metadata) >= 1024:
            _metadata.pop(next(iter(_metadata)))
        _metadata[key] = (monotonic() + 3600, result)
    return result


def parsed_date(value: Any) -> date | None:
    """Treat missing/invalid TMDB dates as unknown rather than released."""
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def regular_episodes(
    details: dict[str, Any], tmdb_id: int, language: str,
) -> list[EpisodeRef]:
    """Batch regular seasons below TMDB's 20-append limit; omit specials/unknown dates."""
    episodes: dict[tuple[int, int], EpisodeRef] = {}
    raw_seasons: Any = details.get("seasons")
    if not isinstance(raw_seasons, list) or any(
        not isinstance(season, dict) for season in raw_seasons
    ):
        raise RuntimeError("TMDB returned an incomplete show catalog")
    seasons: list[int] = sorted({
        season["season_number"] for season in raw_seasons
        if isinstance(season.get("season_number"), int) and season["season_number"] > 0
    })
    for start in range(0, len(seasons), 15):
        batch: list[int] = seasons[start:start + 15]
        appended: str = ",".join(f"season/{number}" for number in batch)
        catalog: dict[str, Any] = metadata(
            f"/tv/{tmdb_id}?append_to_response={appended}", language,
        )
        for number in batch:
            data: Any = catalog.get(f"season/{number}")
            if not isinstance(data, dict) or not isinstance(data.get("episodes"), list):
                raise RuntimeError("TMDB returned an incomplete season catalog")
            for episode in data["episodes"]:
                if not isinstance(episode, dict):
                    raise RuntimeError("TMDB returned an invalid episode")
                episode_number = episode.get("episode_number")
                air_date = parsed_date(episode.get("air_date"))
                if not isinstance(episode_number, int) or episode_number <= 0 or not air_date:
                    continue
                episodes[(number, episode_number)] = EpisodeRef(
                    season_number=number, episode_number=episode_number,
                    name=episode.get("name") or "", air_date=air_date,
                )
    return sorted(
        episodes.values(), key=lambda item: (item.season_number, item.episode_number),
    )


def build_title(
    source: TitleSource,
    language: str, today: date,
) -> TitleResult:
    """Calculate released progress and the next announced regular release."""
    media_type, tmdb_id, cutoff, watched = source
    details: dict[str, Any] = metadata(f"/{media_type}/{tmdb_id}", language)
    base: dict[str, Any] = dict(
        tmdb_id=tmdb_id, media_type=media_type,
        title=details.get("title") or details.get("name") or "",
        poster_path=details.get("poster_path") or "",
        backdrop_path=details.get("backdrop_path") or "",
        tracked=cutoff is not None, status=details.get("status") or "",
    )
    if media_type == "movie":
        release: date | None = parsed_date(details.get("release_date"))
        premiere: NextEntry | None = (
            NextEntry(**base, date=release) if release and release > today else None
        )
        return None, premiere, None
    episodes: list[EpisodeRef] = regular_episodes(details, tmdb_id, language)
    future: list[EpisodeRef] = sorted(
        (ep for ep in episodes if ep.air_date > today),
        key=lambda ep: (ep.air_date, ep.season_number, ep.episode_number),
    )
    if cutoff is None:
        # Bookmarks are a release queue, never assumed viewing progress.
        next_release: NextEntry | None = (
            NextEntry(**base, date=future[0].air_date, episode=future[0])
            if future else None
        )
        return None, next_release, None
    aired: list[EpisodeRef] = [ep for ep in episodes if ep.air_date <= today]
    missing: list[EpisodeRef] = [
        ep for ep in aired
        if ep.air_date > cutoff
        and (ep.season_number, ep.episode_number) not in watched
    ]
    progress: dict[str, int] = dict(
        remaining=len(missing), watched_episodes=len(aired) - len(missing),
        aired_episodes=len(aired),
    )
    upcoming: NextEntry | None = (
        NextEntry(**base, **progress, date=future[0].air_date, episode=future[0])
        if future else None
    )
    if missing:
        ready: NextEntry = NextEntry(
            **base, **progress, date=missing[0].air_date, episode=missing[0],
        )
        return ready, upcoming, None
    caught_up: NextEntry = NextEntry(
        **base, **progress, date=future[0].air_date if future else None,
    )
    return None, upcoming, caught_up


def safe_title(
    source: TitleSource, language: str, today: date,
) -> TitleResult | None:
    """Isolate a metadata failure without manufacturing an empty or caught-up show."""
    try:
        return build_title(source, language, today)
    except (RuntimeError, ValueError, KeyError, TypeError):
        # Do not retain an incomplete appended response for the entire TTL.
        prefix: str = f"/{source[0]}/{source[1]}"
        with _cache_lock:
            for key in list(_metadata):
                path, cached_language = key
                if cached_language == language and (
                    path == prefix or path.startswith((prefix + "?", prefix + "/"))
                ):
                    del _metadata[key]
        return None


def release_feed(db: Session, user_id: UUID, language: str) -> NextFeed:
    """Read private sources in one session, then hydrate public metadata in bounded workers."""
    today: date = utc_today()
    progress = db.scalars(select(ShowProgress).where(
        ShowProgress.user_id == user_id,
    )).all()
    explicit = db.scalars(select(EpisodeProgress).where(
        EpisodeProgress.user_id == user_id,
    )).all()
    watched: dict[int, set[tuple[int, int]]] = {}
    for row in explicit:
        watched.setdefault(row.tmdb_id, set()).add((row.season_number, row.episode_number))
    sources: dict[tuple[str, int], TitleSource] = {
        ("tv", row.tmdb_id): (
            "tv", row.tmdb_id, row.caught_up_through,
            frozenset(watched.get(row.tmdb_id, set())),
        )
        for row in progress
    }
    bookmarks = db.scalars(
        select(Media).join(Watchlist, Media.watchlist_id == Watchlist.id).where(
            Watchlist.author_id == user_id, Watchlist.type == "SYSTEM",
            Media.type == "PENDING",
        )
    ).all()
    for row in bookmarks:
        if row.media_type in ("movie", "tv"):
            sources.setdefault(
                (row.media_type, row.tmdb_id),
                (row.media_type, row.tmdb_id, None, frozenset()),
            )
    exclusions = db.scalars(select(ShowExclusion).where(
        ShowExclusion.user_id == user_id,
    ).order_by(ShowExclusion.title, ShowExclusion.tmdb_id)).all()
    for row in exclusions:
        sources.pop(("tv", row.tmdb_id), None)
    feed: NextFeed = NextFeed(
        user_id=user_id, as_of=today, to_watch=[], upcoming=[], caught_up=[],
        excluded=[ExcludedShow.model_validate(row) for row in exclusions],
    )
    results = _workers.map(
        partial(safe_title, language=language, today=today), sources.values(),
    )
    for result in results:
        if result is None:
            feed.unavailable += 1
            continue
        next_episode, upcoming, caught_up = result
        if next_episode:
            feed.to_watch.append(next_episode)
        if upcoming:
            feed.upcoming.append(upcoming)
        if caught_up:
            if caught_up.status in ("Ended", "Canceled"):
                feed.finished.append(caught_up)
            else:
                feed.caught_up.append(caught_up)
    feed.to_watch.sort(key=lambda item: (item.date or date.max, item.title, item.tmdb_id))
    feed.upcoming.sort(key=lambda item: (
        item.date or date.max, item.title, item.media_type, item.tmdb_id,
    ))
    feed.caught_up.sort(key=lambda item: (item.date or date.max, item.title, item.tmdb_id))
    feed.finished.sort(key=lambda item: (item.title, item.tmdb_id))
    return feed


def initialize_tracking(db: Session, user_id: UUID, tmdb_id: int) -> None:
    """Start from zero without overwriting an existing cutoff or creating history.

    Args:
        db: Request-scoped transaction.
        user_id: Authenticated owner.
        tmdb_id: Server-verified show identity.
    """
    db.execute(insert(ShowProgress).values(
        user_id=user_id, tmdb_id=tmdb_id, caught_up_through=date.min,
    ).on_conflict_do_nothing())


def show_progress(db: Session, user_id: UUID, tmdb_id: int) -> ShowProgressState:
    """Read released episode states without creating progress or assuming history."""
    today: date = utc_today()
    try:
        episodes: list[EpisodeRef] = regular_episodes(
            metadata(f"/tv/{tmdb_id}", "en-US"), tmdb_id, "en-US",
        )
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(503, "Episode metadata unavailable; try again") from error
    progress: ShowProgress | None = db.scalar(select(ShowProgress).where(
        ShowProgress.user_id == user_id, ShowProgress.tmdb_id == tmdb_id,
    ))
    rows: list[EpisodeProgress] = list(db.scalars(select(EpisodeProgress).where(
        EpisodeProgress.user_id == user_id, EpisodeProgress.tmdb_id == tmdb_id,
    )).all())
    watched: set[tuple[int, int]] = {(row.season_number, row.episode_number) for row in rows}
    return ShowProgressState(
        user_id=user_id, tmdb_id=tmdb_id, as_of=today, tracked=progress is not None,
        episodes=[WatchedEpisodeState(
            season_number=ep.season_number, episode_number=ep.episode_number,
            watched=progress is not None and (
                ep.air_date <= progress.caught_up_through
                or (ep.season_number, ep.episode_number) in watched
            ),
        ) for ep in episodes if ep.air_date <= today],
    )


def start_tracking(db: Session, user_id: UUID, tmdb_id: int) -> None:
    """Verify the show before creating an empty, idempotent tracking baseline."""
    try:
        details: dict[str, Any] = metadata(f"/tv/{tmdb_id}", "en-US")
        if details.get("id") != tmdb_id:
            raise RuntimeError("Invalid show identity")
    except RuntimeError as error:
        raise HTTPException(503, "Show metadata unavailable; try again") from error
    initialize_tracking(db, user_id, tmdb_id)
    db.commit()


def mark_season(
    db: Session, user_id: UUID, tmdb_id: int, season_number: int, through: date,
) -> None:
    """Mark only this season's released episodes through the displayed UTC date."""
    if through > utc_today():
        raise HTTPException(422, "Cannot mark future episodes watched")
    episodes: list[dict[str, Any]] = season_catalog(tmdb_id, season_number)
    released: set[int] = set()
    for episode in episodes:
        number: Any = episode.get("episode_number")
        air_date: date | None = parsed_date(episode.get("air_date"))
        if (isinstance(number, int) and not isinstance(number, bool)
                and number > 0 and air_date is not None and air_date <= through):
            released.add(number)
    if not released:
        raise HTTPException(422, "No released regular episodes in this season")
    initialize_tracking(db, user_id, tmdb_id)
    db.execute(insert(EpisodeProgress).values([
        dict(
            user_id=user_id, tmdb_id=tmdb_id, season_number=season_number,
            episode_number=number,
        ) for number in sorted(released)
    ]).on_conflict_do_nothing())
    db.commit()


def season_catalog(tmdb_id: int, season_number: int) -> list[dict[str, Any]]:
    """Verify a complete season before any progress is written."""
    try:
        season: dict[str, Any] = metadata(f"/tv/{tmdb_id}/season/{season_number}", "en-US")
    except RuntimeError as error:
        raise HTTPException(503, "Episode metadata unavailable; try again") from error
    episodes: Any = season.get("episodes")
    if not isinstance(episodes, list) or any(not isinstance(item, dict) for item in episodes):
        raise HTTPException(503, "Episode metadata unavailable; try again")
    return episodes


def mark_episode(db: Session, user_id: UUID, tmdb_id: int, episode: EpisodeWatched) -> None:
    """Mark one verified aired episode, starting tracking without assuming its neighbors."""
    season_episodes: list[dict[str, Any]] = season_catalog(tmdb_id, episode.season_number)
    match: dict[str, Any] | None = next((
        item for item in season_episodes
        if item.get("episode_number") == episode.episode_number
    ), None)
    air_date: date | None = parsed_date(match.get("air_date")) if match else None
    if not air_date or air_date > utc_today():
        raise HTTPException(422, "Only released regular episodes can be marked watched")
    initialize_tracking(db, user_id, tmdb_id)
    db.execute(insert(EpisodeProgress).values(
        user_id=user_id, tmdb_id=tmdb_id, season_number=episode.season_number,
        episode_number=episode.episode_number,
    ).on_conflict_do_nothing())
    db.commit()


def catch_up(db: Session, user_id: UUID, tmdb_id: int, through: date) -> None:
    """Mark released regular episodes caught up using an explicit, retry-stable cutoff."""
    if through > utc_today():
        raise HTTPException(422, "Cannot mark future episodes watched")
    progress = db.scalar(select(ShowProgress).where(
        ShowProgress.user_id == user_id, ShowProgress.tmdb_id == tmdb_id,
    ).with_for_update())
    if progress is None:
        raise HTTPException(404, "Tracked show not found")
    progress.caught_up_through = max(progress.caught_up_through, through)
    db.commit()


def exclude_show(
    db: Session, user_id: UUID, tmdb_id: int, snapshot: ShowExclusionRequest,
) -> None:
    """Idempotently save a private exclusion without touching tracking sources.

    Args:
        db: Request-scoped database session.
        user_id: Authenticated cookie owner.
        tmdb_id: TV identity to hide, never a movie identity.
        snapshot: Display-only title/poster copy for reliable offline metadata fallback.
    """
    db.execute(insert(ShowExclusion).values(
        user_id=user_id, tmdb_id=tmdb_id, title=snapshot.title,
        poster_path=snapshot.poster_path,
    ).on_conflict_do_nothing())
    db.commit()


def restore_show(db: Session, user_id: UUID, tmdb_id: int) -> None:
    """Idempotently clear only this owner's exclusion, keeping all episode progress."""
    db.execute(delete(ShowExclusion).where(
        ShowExclusion.user_id == user_id, ShowExclusion.tmdb_id == tmdb_id,
    ))
    db.commit()
