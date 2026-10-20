"""Rehearse derived viewing activity on an owned disposable PostgreSQL only.

Uses generated fixtures and stored public metadata, never configured application
settings, real accounts, TMDB, push transport or the production database.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

ROOT: Path = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "contract_tests")]
from test_up_next import service
from app.database.base import Base
from app.models import EpisodeProgress, Media, ReleaseCatalog, ShowProgress, User, View, Watchlist
from app.schemas.up_next import EpisodeWatched, ProgressActionRequest, ShowExclusionRequest
from app.services import release_catalog_service as catalogs
from app.services import progress_action_service as actions
from app.services.notification_service import release_notices_today


def run() -> None:
    """Preserve legacy rows while exercising bookmark/progress/removal transitions."""
    name: str = f"scenario-activity-test-{uuid4().hex[:12]}"
    subprocess.run(["docker", "run", "--detach", "--rm", "--pull", "never", "--name", name,
                    "--tmpfs", "/var/lib/postgresql/data", "--publish", "127.0.0.1::5432",
                    "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "--env", "POSTGRES_DB=activity_test",
                    "postgres:16-alpine"], check=True, capture_output=True)
    engine = None
    try:
        port: str = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        engine = create_engine(f"postgresql+psycopg2://postgres@127.0.0.1:{port}/activity_test")
        for attempt in range(60):
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                break
            except OperationalError:
                if attempt == 59:
                    raise
                time.sleep(1)
        Base.metadata.create_all(engine)
        owner, other = uuid4(), uuid4()
        day: date = service.utc_today()
        now: datetime = datetime.now(timezone.utc)
        payload: dict = {"id": 42, "name": "Fixture show", "genres": [{"id": 18}], "first_air_date": "2020-01-01", "status": "Returning Series", "number_of_episodes": 3,
                         "seasons": [{"season_number": 1}], "season/1": {"season_number": 1, "episodes": [
                             {"episode_number": 1, "name": "One", "air_date": "2020-01-01"},
                             {"episode_number": 2, "name": "Two", "air_date": day.isoformat()},
                             {"episode_number": 3, "name": "Three", "air_date": (day + timedelta(days=7)).isoformat()},
                         ]}}
        with Session(engine) as db, patch.object(catalogs, "TmdbService", side_effect=AssertionError("No upstream request permitted")):
            for identity in (owner, other):
                db.add(User(id=identity, username=f"fixture-{identity}", email=f"{identity}@example.test", hashed_password="fixture"))
            db.flush()
            historical: dict = dict(tmdb_id=99, title="Legacy show", media_type="tv", viewer_id=other, poster_path="", backdrop_path="", genre_ids=[0, 18], release_date="2020-01-01", release_year="2020", runtime=500, recorded_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
            db.add(View(**historical))
            db.add(ShowProgress(user_id=other, tmdb_id=99, caught_up_through=day))
            db.add(ReleaseCatalog(media_type="tv", tmdb_id=99, language="en-US", payload={**payload, "id": 99}, next_refresh_at=now + timedelta(hours=6)))
            db.add(ReleaseCatalog(media_type="tv", tmdb_id=42, language="en-US", payload=payload, next_refresh_at=now + timedelta(hours=6)))
            db.add(ReleaseCatalog(media_type="movie", tmdb_id=42, language="en-US", payload={"id": 42, "title": "Fixture film", "release_date": day.isoformat()}, next_refresh_at=now + timedelta(hours=6)))
            queue = Watchlist(title="Bookmarks", type="SYSTEM", author_id=owner)
            custom = Watchlist(title="Not an intention", type="CUSTOM", author_id=owner)
            db.add_all([queue, custom])
            db.flush()
            media: dict = dict(type="PENDING", tmdb_id=42, title="Fixture", poster_path="", backdrop_path="", release_date=day.isoformat(), runtime=3, genre_ids=[18])
            db.add(Media(**media, media_type="tv", watchlist_id=custom.id))
            db.commit()
            baseline: list = db.execute(select(View.__table__).order_by(View.id)).all()
            assert service.release_feed(db, owner, "en-US").to_watch == []
            assert service.viewed_shows(db, owner, "en-US").shows == []
            for kind in ("tv", "movie"):
                db.add(Media(**media, media_type=kind, watchlist_id=queue.id))
            db.commit()
            feed = service.release_feed(db, owner, "en-US")
            assert {(entry.media_type, entry.tmdb_id) for entry in feed.to_watch} == {("tv", 42), ("movie", 42)}
            assert next(entry for entry in feed.to_watch if entry.media_type == "tv").watched_episodes == 0
            assert service.viewed_shows(db, owner, "en-US").shows == []
            assert len(release_notices_today(db, owner, "en-US", day)) == 2
            bookmark_tv = db.scalar(select(Media).where(Media.watchlist_id == queue.id, Media.media_type == "tv"))
            db.delete(bookmark_tv)
            db.commit()
            assert [entry.media_type for entry in service.release_feed(db, owner, "en-US").to_watch] == ["movie"]
            service.mark_episode(db, owner, 42, EpisodeWatched(season_number=1, episode_number=1, watched=True))
            projected = service.viewed_shows(db, owner, "en-US")
            assert len(projected.shows) == 1 and projected.shows[0].watched_episodes == 1 and projected.shows[0].status == "in_progress"
            assert db.execute(select(View.__table__).order_by(View.id)).all() == baseline
            assert next(entry for entry in service.release_feed(db, owner, "en-US").to_watch if entry.media_type == "tv").episode.episode_number == 2
            assert len(release_notices_today(db, owner, "en-US", day)) == 2
            service.exclude_show(db, owner, 42, ShowExclusionRequest(title="Fixture", poster_path=""))
            assert [entry.media_type for entry in service.release_feed(db, owner, "en-US").to_watch] == ["movie"]
            assert len(service.viewed_shows(db, owner, "en-US").shows) == 1
            assert len(release_notices_today(db, owner, "en-US", day)) == 1
            service.restore_show(db, owner, 42)
            service.mark_season(db, owner, 42, 1, day, True)
            assert service.viewed_shows(db, owner, "en-US").shows[0].status == "caught_up"
            service.mark_season(db, owner, 42, 1, day, False)
            assert service.viewed_shows(db, owner, "en-US").shows == []
            assert [entry.media_type for entry in service.release_feed(db, owner, "en-US").to_watch] == ["movie"]
            assert len(release_notices_today(db, owner, "en-US", day)) == 1
            assert db.get(ShowProgress, (owner, 42)) is not None  # dormant, never destructive cleanup
            db.add(Media(**media, media_type="tv", watchlist_id=queue.id))
            db.commit()
            assert next(entry for entry in service.release_feed(db, owner, "en-US").to_watch if entry.media_type == "tv").episode.episode_number == 1
            service.mark_show(db, owner, 42, day, True, record_history=True)
            assert len(service.viewed_shows(db, owner, "en-US").shows) == 1
            service.mark_show(db, owner, 42, day, False, record_history=True)
            assert service.viewed_shows(db, owner, "en-US").shows == []
            assert any(entry.media_type == "tv" for entry in service.release_feed(db, owner, "en-US").to_watch)
            db.delete(db.scalar(select(Media).where(Media.watchlist_id == queue.id, Media.media_type == "tv")))
            db.commit()
            assert not any(entry.media_type == "tv" for entry in service.release_feed(db, owner, "en-US").to_watch)
            assert db.execute(select(View.__table__).order_by(View.id)).all() == baseline
            assert service.viewed_shows(db, other, "en-US").shows[0].tmdb_id == 99
            db.add(View(**{**historical, "tmdb_id": 42, "media_type": "movie", "viewer_id": owner}))
            db.commit()
            assert service.release_feed(db, owner, "en-US").to_watch == []
            assert release_notices_today(db, owner, "en-US", day) == []
            assert not db.scalars(select(EpisodeProgress).where(EpisodeProgress.user_id == other)).all()
            # Queued cold choices must keep both projections polling without
            # manufacturing watched activity before catalogue validation applies.
            stable_history: list = db.execute(select(View.__table__).order_by(View.id)).all()
            intent = ProgressActionRequest(id=uuid4(), season_number=1, episode_number=1, watched=True, through=day, record_history=False)
            assert actions.submit_action(db, owner, 88, intent).status == "pending"
            assert service.release_feed(db, owner, "en-US").syncing
            assert service.viewed_shows(db, owner, "en-US").syncing
            assert service.viewed_shows(db, owner, "en-US").shows == []
            row = db.get(ReleaseCatalog, ("tv", 88, "en-US"))
            row.payload = {**payload, "id": 88}
            db.commit()
            actions.drain_ready_actions(db)
            assert [entry.tmdb_id for entry in service.viewed_shows(db, owner, "en-US").shows] == [88]
            assert db.execute(select(View.__table__).order_by(View.id)).all() == stable_history
        print("Viewing activity PostgreSQL rehearsal passed: bookmarks, partial/season/show activity, no-reference removal, dormant negative overrides, movie/TV identity, exclusions, notifications, owner isolation and unchanged legacy history/statistics inputs. No schema migration required.")
    finally:
        if engine is not None:
            engine.dispose()
        subprocess.run(["docker", "stop", name], check=True, capture_output=True)


if __name__ == "__main__":
    run()
