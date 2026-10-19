"""Database-only request reads; public TMDB retrieval belongs to the worker."""

from datetime import datetime, timedelta, timezone
import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Media, ReleaseCatalog, ShowProgress, Watchlist
from app.services.tmdb_service import TmdbService


class CatalogPending(RuntimeError):
    """A complete catalogue has not been published yet."""


def request_catalog(db: Session, media_type: str, tmdb_id: int, language: str, priority: int = 0) -> None:
    """Enqueue one shared identity without replacing data or resetting an existing job."""
    statement = insert(ReleaseCatalog).values(
        media_type=media_type, tmdb_id=tmdb_id, language=language,
        next_refresh_at=datetime.now(timezone.utc), priority=priority,
    )
    if priority:
        # Never reset a healthy snapshot's schedule just because someone visited it.
        db.execute(statement.on_conflict_do_update(
            index_elements=[ReleaseCatalog.media_type, ReleaseCatalog.tmdb_id, ReleaseCatalog.language],
            set_={"priority": func.greatest(ReleaseCatalog.priority, priority)},
            where=ReleaseCatalog.payload.is_(None),
        ))
    else:
        db.execute(statement.on_conflict_do_nothing())


def preload_catalogs(db: Session, identities: list[tuple[str, int]], language: str) -> None:
    """Load a feed's public snapshots in one query instead of one query per show."""
    if not identities:
        return
    rows: list[ReleaseCatalog] = list(db.scalars(select(ReleaseCatalog).where(
        ReleaseCatalog.language == language,
        tuple_(ReleaseCatalog.media_type, ReleaseCatalog.tmdb_id).in_(identities),
    )).all())
    indexed: dict[tuple[str, int, str], ReleaseCatalog | None] = {
        (row.media_type, row.tmdb_id, row.language): row for row in rows
    }
    missing: list[tuple[str, int]] = [key for key in identities if (*key, language) not in indexed]
    if missing:
        now: datetime = datetime.now(timezone.utc)
        db.execute(insert(ReleaseCatalog).values([
            dict(media_type=kind, tmdb_id=number, language=language, next_refresh_at=now, priority=5)
            for kind, number in missing
        ]).on_conflict_do_nothing())
        db.commit()
        # Commit expires ORM rows. Reload the set once, not lazily per title.
        rows = list(db.scalars(select(ReleaseCatalog).where(
            ReleaseCatalog.language == language,
            tuple_(ReleaseCatalog.media_type, ReleaseCatalog.tmdb_id).in_(identities),
        )).all())
        indexed = {(row.media_type, row.tmdb_id, row.language): row for row in rows}
    db.info["release_catalog_reads"] = indexed


def stored_metadata(db: Session, path: str, language: str) -> dict[str, Any]:
    """Read a complete public snapshot, queuing only a first encounter on cache miss."""
    match: re.Match[str] | None = re.fullmatch(r"/(tv|movie)/(\d+)(?:/season/(\d+)|\?append_to_response=.+)?", path)
    if not match:
        raise RuntimeError("Unsupported catalogue path")
    media_type, identity, season = match.groups()
    key: tuple[str, int, str] = (media_type, int(identity), language)
    reads: dict[tuple[str, int, str], ReleaseCatalog | None] = db.info.setdefault("release_catalog_reads", {})
    if key not in reads:
        row: ReleaseCatalog | None = db.get(ReleaseCatalog, key)
        if row is None:
            request_catalog(db, *key, priority=10)
            db.commit()  # Only a public job; no progress/history writes have begun.
            row = db.get(ReleaseCatalog, key)
        reads[key] = row
    row = reads[key]
    if row is None or row.payload is None:
        if row is not None and row.failed_at is not None:
            raise RuntimeError("Release catalogue refresh failed; try again")
        raise CatalogPending("Release catalogue is being prepared")
    if season is not None:
        value: Any = row.payload.get(f"season/{season}")
        if not isinstance(value, dict):
            raise RuntimeError("Season not in published catalogue")
        return value
    return row.payload


def refresh_owner_catalogs(db: Session, user_id: UUID, language: str) -> None:
    """Queue this owner's sources, deduplicating repeated refreshes and active leases."""
    identities: set[tuple[str, int]] = {
        ("tv", number) for number in db.scalars(select(ShowProgress.tmdb_id).where(ShowProgress.user_id == user_id)).all()
    }
    identities.update(db.execute(select(Media.media_type, Media.tmdb_id).join(
        Watchlist, Media.watchlist_id == Watchlist.id,
    ).where(Watchlist.author_id == user_id, Watchlist.type == "SYSTEM", Media.type == "PENDING", Media.media_type.in_(("tv", "movie")))).all())
    now: datetime = datetime.now(timezone.utc)
    for media_type, tmdb_id in sorted(identities):
        request_catalog(db, media_type, tmdb_id, language)
        row: ReleaseCatalog = db.scalars(select(ReleaseCatalog).where(
            ReleaseCatalog.media_type == media_type, ReleaseCatalog.tmdb_id == tmdb_id,
            ReleaseCatalog.language == language,
        ).with_for_update()).one()
        if (row.leased_until is None or row.leased_until <= now) and row.next_refresh_at > now and (
            row.updated_at is None or row.updated_at < now - timedelta(minutes=1)
        ):
            row.next_refresh_at = now
            row.failed_at = None
    db.commit()


def seed_catalogs(db: Session) -> None:
    """Warm both supported languages for tracked shows and pending system Bookmarks."""
    identities: set[tuple[str, int]] = {("tv", number) for number in db.scalars(select(ShowProgress.tmdb_id).distinct()).all()}
    identities.update(db.execute(select(Media.media_type, Media.tmdb_id).join(
        Watchlist, Media.watchlist_id == Watchlist.id,
    ).where(Watchlist.type == "SYSTEM", Media.type == "PENDING", Media.media_type.in_(("tv", "movie"))).distinct()).all())
    for media_type, tmdb_id in sorted(identities):
        for language in ("en-US", "fr-FR"):
            request_catalog(db, media_type, tmdb_id, language)
    db.commit()


def claim_catalog(db: Session) -> tuple[str, int, str, datetime] | None:
    """Atomically lease one due job across API processes; recover abandoned leases."""
    now: datetime = datetime.now(timezone.utc)
    row: ReleaseCatalog | None = db.scalar(select(ReleaseCatalog).where(
        ReleaseCatalog.next_refresh_at <= now,
        or_(ReleaseCatalog.leased_until.is_(None), ReleaseCatalog.leased_until <= now),
    ).order_by(ReleaseCatalog.priority.desc(), ReleaseCatalog.next_refresh_at).with_for_update(skip_locked=True).limit(1))
    if row is None:
        db.rollback()
        return None
    row.leased_until = now + timedelta(minutes=15)
    identity: tuple[str, int, str, datetime] = (row.media_type, row.tmdb_id, row.language, row.leased_until)
    db.commit()
    return identity


def fetch_catalog(media_type: str, tmdb_id: int, language: str) -> dict[str, Any]:
    """Fetch and validate every regular season before atomically publishing a title."""
    client: TmdbService = TmdbService()
    details: dict[str, Any] = client.get_release_details(f"/{media_type}/{tmdb_id}", language)
    if not isinstance(details, dict) or type(details.get("id")) is not int or details["id"] != tmdb_id:
        raise RuntimeError("Invalid title identity")
    for field in ("title", "name", "poster_path", "backdrop_path", "status"):
        if details.get(field) is not None and not isinstance(details[field], str):
            raise RuntimeError("Invalid title metadata")
    if media_type == "movie":
        return compact_catalog(details)
    raw: Any = details.get("seasons")
    if not isinstance(raw, list) or any(not isinstance(season, dict) for season in raw):
        raise RuntimeError("Incomplete season list")
    seasons: list[int] = sorted({season["season_number"] for season in raw
        if type(season.get("season_number")) is int and season["season_number"] > 0})
    for offset in range(0, len(seasons), 15):
        batch: list[int] = seasons[offset:offset + 15]
        appended: str = ",".join(f"season/{number}" for number in batch)
        data: dict[str, Any] = client.get_release_details(f"/tv/{tmdb_id}?append_to_response={appended}", language)
        if not isinstance(data, dict) or data.get("id") != tmdb_id:
            raise RuntimeError("Invalid appended show identity")
        for number in batch:
            season: Any = data.get(f"season/{number}")
            if (not isinstance(season, dict) or type(season.get("season_number")) is not int
                    or season["season_number"] != number or not isinstance(season.get("episodes"), list)):
                raise RuntimeError("Incomplete season catalogue")
            seen: set[int] = set()
            for episode in season["episodes"]:
                if (not isinstance(episode, dict) or type(episode.get("episode_number")) is not int
                        or episode["episode_number"] <= 0 or episode["episode_number"] in seen):
                    raise RuntimeError("Invalid episode identity")
                if episode.get("name") is not None and not isinstance(episode["name"], str):
                    raise RuntimeError("Invalid episode metadata")
                seen.add(episode["episode_number"])
            details[f"season/{number}"] = season
    return compact_catalog(details)


def compact_catalog(details: dict[str, Any]) -> dict[str, Any]:
    """Store only release/history fields, not cast, synopses or per-episode crew lists."""
    fields: tuple[str, ...] = (
        "id", "name", "title", "poster_path", "backdrop_path", "status", "seasons",
        "release_date", "first_air_date", "number_of_episodes", "genres",
    )
    result: dict[str, Any] = {key: details[key] for key in fields if key in details}
    for key, value in details.items():
        if key.startswith("season/"):
            result[key] = {
                "season_number": value["season_number"],
                "episodes": [{field: ep.get(field) for field in ("episode_number", "air_date", "name")} for ep in value["episodes"]],
            }
    if isinstance(result.get("seasons"), list):
        result["seasons"] = [{"season_number": season["season_number"]} for season in result["seasons"] if type(season.get("season_number")) is int and season["season_number"] > 0]
    return result


def publish_catalog(db: Session, identity: tuple[str, int, str, datetime], payload: dict[str, Any] | None) -> None:
    """Fence expired workers and preserve the last good snapshot after failure."""
    row: ReleaseCatalog | None = db.scalar(select(ReleaseCatalog).where(
        ReleaseCatalog.media_type == identity[0], ReleaseCatalog.tmdb_id == identity[1],
        ReleaseCatalog.language == identity[2], ReleaseCatalog.leased_until == identity[3],
    ).with_for_update())
    if row is None:
        db.rollback()
        return
    now: datetime = datetime.now(timezone.utc)
    if payload is not None:
        row.payload = payload
        row.updated_at = now
        row.failed_at = None
        row.priority = 0
        hours: int = 168 if payload.get("status") in ("Ended", "Canceled") else 6
        row.next_refresh_at = now + timedelta(hours=hours)
    else:
        row.failed_at = now
        row.next_refresh_at = now + timedelta(minutes=5)
    row.leased_until = None
    db.commit()
