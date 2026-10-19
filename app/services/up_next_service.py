"""Combine owner-scoped progress with cached public TMDB release metadata."""

from datetime import date, datetime, timezone
from typing import Any, TypeAlias
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import EpisodeProgress, Media, ShowExclusion, ShowProgress, View, Watchlist
from app.schemas.up_next import (
    ExcludedShow, EpisodeRef, EpisodeWatched, NextEntry, NextFeed,
    ShowExclusionRequest, ShowProgressState, WatchedEpisodeState,
)
from app.services.release_catalog_service import CatalogPending, preload_catalogs, stored_metadata

EpisodeKeys: TypeAlias = frozenset[tuple[int, int]]
TitleSource: TypeAlias = (
    tuple[str, int, date | None, EpisodeKeys]
    | tuple[str, int, date | None, EpisodeKeys, EpisodeKeys]
)
TitleResult: TypeAlias = tuple[NextEntry | None, NextEntry | None, NextEntry | None]


def utc_today() -> date:
    """Return the date used consistently for release and baseline comparisons."""
    return datetime.now(timezone.utc).date()


def metadata(path: str, language: str, db: Session | None = None) -> dict[str, Any]:
    """Read persisted public metadata; upstream retrieval is forbidden on this path."""
    if db is None:
        raise RuntimeError("A catalogue database session is required")
    return stored_metadata(db, path, language)


def parsed_date(value: Any) -> date | None:
    """Treat missing/invalid TMDB dates as unknown rather than released."""
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def regular_episodes(
    details: dict[str, Any], tmdb_id: int, language: str, db: Session | None = None,
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
            f"/tv/{tmdb_id}?append_to_response={appended}", language, db,
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
    language: str, today: date, db: Session | None = None,
) -> TitleResult:
    """Calculate released progress and the next announced regular release."""
    media_type, tmdb_id, cutoff, watched = source[:4]
    unwatched: EpisodeKeys = source[4] if len(source) == 5 else frozenset()
    details: dict[str, Any] = metadata(f"/{media_type}/{tmdb_id}", language, db)
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
    episodes: list[EpisodeRef] = regular_episodes(details, tmdb_id, language, db)
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
        if (ep.season_number, ep.episode_number) in unwatched or (
            ep.air_date > cutoff and (ep.season_number, ep.episode_number) not in watched
        )
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
    source: TitleSource, language: str, today: date, db: Session | None = None,
) -> TitleResult | None:
    """Isolate a metadata failure without manufacturing an empty or caught-up show."""
    try:
        return build_title(source, language, today, db)
    except (RuntimeError, ValueError, KeyError, TypeError):
        return None


def release_feed(db: Session, user_id: UUID, language: str) -> NextFeed:
    """Read private sources in one session, then hydrate public metadata in bounded workers."""
    db.info.pop("release_catalog_reads", None)
    today: date = utc_today()
    progress = db.scalars(select(ShowProgress).where(
        ShowProgress.user_id == user_id,
    )).all()
    explicit = db.scalars(select(EpisodeProgress).where(
        EpisodeProgress.user_id == user_id,
    )).all()
    watched: dict[int, set[tuple[int, int]]] = {}
    unwatched: dict[int, set[tuple[int, int]]] = {}
    for row in explicit:
        target = watched if getattr(row, "watched", True) else unwatched
        target.setdefault(row.tmdb_id, set()).add((row.season_number, row.episode_number))
    sources: dict[tuple[str, int], TitleSource] = {
        ("tv", row.tmdb_id): (
            "tv", row.tmdb_id, row.caught_up_through,
            frozenset(watched.get(row.tmdb_id, set())),
            frozenset(unwatched.get(row.tmdb_id, set())),
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
    preload_catalogs(db, list(sources), language)
    feed: NextFeed = NextFeed(
        user_id=user_id, as_of=today, to_watch=[], upcoming=[], caught_up=[],
        excluded=[ExcludedShow.model_validate(row) for row in exclusions],
    )
    # Database-only reads: never share a request session with executor threads.
    results = (safe_title(source, language, today, db) for source in sources.values())
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
    reads = db.info.get("release_catalog_reads", {}).values()
    now: datetime = datetime.now(timezone.utc)
    dates: list[datetime] = [
        row.updated_at for row in reads
        if row is not None and row.updated_at is not None
    ]
    feed.updated_at = min(dates) if dates else None
    feed.syncing = any(
        row is None or (row.failed_at is None and row.next_refresh_at <= now)
        or row.leased_until is not None for row in reads
    )
    feed.sync_failed = any(row is not None and row.failed_at is not None for row in reads)
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
    db.info.pop("release_catalog_reads", None)
    today: date = utc_today()
    ready: bool = True
    try:
        episodes: list[EpisodeRef] = regular_episodes(
            metadata(f"/tv/{tmdb_id}", "en-US", db), tmdb_id, "en-US", db,
        )
    except CatalogPending:
        ready = False
        episodes = []
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(503, "Episode metadata unavailable; try again") from error
    progress: ShowProgress | None = db.scalar(select(ShowProgress).where(
        ShowProgress.user_id == user_id, ShowProgress.tmdb_id == tmdb_id,
    ))
    rows: list[EpisodeProgress] = list(db.scalars(select(EpisodeProgress).where(
        EpisodeProgress.user_id == user_id, EpisodeProgress.tmdb_id == tmdb_id,
    )).all())
    overrides: dict[tuple[int, int], bool] = {
        (row.season_number, row.episode_number): row.watched for row in rows
    }
    return ShowProgressState(
        user_id=user_id, tmdb_id=tmdb_id, as_of=today, tracked=progress is not None,
        episodes=[WatchedEpisodeState(
            season_number=ep.season_number, episode_number=ep.episode_number,
            air_date=ep.air_date,
            watched=progress is not None and overrides.get(
                (ep.season_number, ep.episode_number), ep.air_date <= progress.caught_up_through,
            ),
        ) for ep in episodes if ep.air_date <= today],
        ready=ready, syncing=not ready,
        updated_at=next((
            row.updated_at for row in db.info.get("release_catalog_reads", {}).values()
            if row is not None
        ), None),
    )


def start_tracking(db: Session, user_id: UUID, tmdb_id: int) -> None:
    """Verify the show before creating an empty, idempotent tracking baseline."""
    try:
        details: dict[str, Any] = metadata(f"/tv/{tmdb_id}", "en-US", db)
        if details.get("id") != tmdb_id:
            raise RuntimeError("Invalid show identity")
    except RuntimeError as error:
        raise HTTPException(503, "Show metadata unavailable; try again") from error
    initialize_tracking(db, user_id, tmdb_id)
    db.commit()


def mark_season(
    db: Session, user_id: UUID, tmdb_id: int, season_number: int, through: date, watched: bool = True,
    *, commit: bool = True,
) -> None:
    """Mark only this season's released episodes through the displayed UTC date."""
    if through > utc_today():
        raise HTTPException(422, "Cannot mark future episodes watched")
    episodes: list[dict[str, Any]] = season_catalog(tmdb_id, season_number, db)
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
    statement = insert(EpisodeProgress).values([
        dict(
            user_id=user_id, tmdb_id=tmdb_id, season_number=season_number,
            episode_number=number, watched=watched,
        ) for number in sorted(released)
    ])
    db.execute(statement.on_conflict_do_update(
        index_elements=[
            EpisodeProgress.user_id, EpisodeProgress.tmdb_id,
            EpisodeProgress.season_number, EpisodeProgress.episode_number,
        ],
        set_={"watched": statement.excluded.watched},
    ))
    if commit:
        db.commit()


def season_catalog(tmdb_id: int, season_number: int, db: Session | None = None) -> list[dict[str, Any]]:
    """Verify a complete season before any progress is written."""
    try:
        season: dict[str, Any] = metadata(f"/tv/{tmdb_id}/season/{season_number}", "en-US", db)
    except RuntimeError as error:
        raise HTTPException(503, "Episode metadata unavailable; try again") from error
    episodes: Any = season.get("episodes")
    if not isinstance(episodes, list) or any(not isinstance(item, dict) for item in episodes):
        raise HTTPException(503, "Episode metadata unavailable; try again")
    return episodes


def mark_episode(db: Session, user_id: UUID, tmdb_id: int, episode: EpisodeWatched, *, commit: bool = True, through: date | None = None) -> None:
    """Mark one verified aired episode, starting tracking without assuming its neighbors."""
    season_episodes: list[dict[str, Any]] = season_catalog(tmdb_id, episode.season_number, db)
    match: dict[str, Any] | None = next((
        item for item in season_episodes
        if item.get("episode_number") == episode.episode_number
    ), None)
    air_date: date | None = parsed_date(match.get("air_date")) if match else None
    if not air_date or air_date > min(through or utc_today(), utc_today()):
        raise HTTPException(422, "Only released regular episodes can be marked watched")
    initialize_tracking(db, user_id, tmdb_id)
    statement = insert(EpisodeProgress).values(
        user_id=user_id, tmdb_id=tmdb_id, season_number=episode.season_number,
        episode_number=episode.episode_number, watched=episode.watched,
    )
    db.execute(statement.on_conflict_do_update(
        index_elements=[
            EpisodeProgress.user_id, EpisodeProgress.tmdb_id,
            EpisodeProgress.season_number, EpisodeProgress.episode_number,
        ],
        set_={"watched": statement.excluded.watched},
    ))
    if commit:
        db.commit()


def mark_show(
    db: Session, user_id: UUID, tmdb_id: int, through: date, watched: bool,
    record_history: bool = False,
    *, commit: bool = True,
) -> None:
    """Set released children; only the explicit show-details action also changes history.

    Args:
        db: Request transaction, shared by the atomic history/progress update.
        user_id: Cookie-authenticated owner.
        tmdb_id: Public show identity verified by the catalogue worker.
        through: Displayed UTC cutoff, never the eventual retry date.
        watched: Desired state, not a toggle evaluated again on retry.
        record_history: Preserve whole-show watched UX; child/feed actions never set this.
    """
    if through > utc_today():
        raise HTTPException(422, "Cannot mark future episodes")
    try:
        details: dict[str, Any] = metadata(f"/tv/{tmdb_id}", "en-US", db)
        episodes: list[EpisodeRef] = regular_episodes(details, tmdb_id, "en-US", db)
    except RuntimeError as error:
        raise HTTPException(503, "Release catalogue unavailable; try again") from error
    released: list[EpisodeRef] = [episode for episode in episodes if episode.air_date <= through]
    if not released:
        raise HTTPException(422, "No released regular episodes")
    if record_history and watched and (
        type(details.get("number_of_episodes")) is not int or details["number_of_episodes"] < 0
        or not isinstance(details.get("name"), str) or not details["name"]
    ):
        raise HTTPException(422, "Incomplete show history metadata")
    initialize_tracking(db, user_id, tmdb_id)
    # Serialize explicit whole-show actions before checking/creating history.
    db.scalar(select(ShowProgress).where(
        ShowProgress.user_id == user_id, ShowProgress.tmdb_id == tmdb_id,
    ).with_for_update())
    if record_history:
        history_scope = (
            View.viewer_id == user_id, View.tmdb_id == tmdb_id,
            View.media_type == "tv",
        )
        if not watched:
            db.execute(delete(View).where(*history_scope))
        elif db.scalar(select(View.id).where(*history_scope).limit(1)) is None:
            first_air: str = details.get("first_air_date") or ""
            genre_ids: list[int] = [
                genre["id"] for genre in details.get("genres", [])
                if isinstance(genre, dict) and type(genre.get("id")) is int
                and genre["id"] != 0
            ]
            db.add(View(
                viewer_id=user_id, tmdb_id=tmdb_id, media_type="tv",
                recorded_at=datetime.now(timezone.utc), title=details["name"],
                poster_path=details.get("poster_path") or "",
                backdrop_path=details.get("backdrop_path") or "",
                release_date=first_air, release_year=first_air[:4],
                runtime=details["number_of_episodes"], genre_ids=[0, *genre_ids],
            ))
    statement = insert(EpisodeProgress).values([
        dict(
            user_id=user_id, tmdb_id=tmdb_id, season_number=ep.season_number,
            episode_number=ep.episode_number, watched=watched,
        )
        for ep in released
    ])
    db.execute(statement.on_conflict_do_update(
        index_elements=[
            EpisodeProgress.user_id, EpisodeProgress.tmdb_id,
            EpisodeProgress.season_number, EpisodeProgress.episode_number,
        ],
        set_={"watched": statement.excluded.watched},
    ))
    if commit:
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
