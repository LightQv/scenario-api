"""Rehearse progress against a disposable, loopback-only PostgreSQL 16 container.

Run from the API root: .venv/bin/python scripts/test_up_next_postgres.py
Uses only the already installed postgres:16-alpine image (--pull never), tmpfs,
generated fixture users and mocked TMDB. Never reads application settings or
connects to any configured Scenario database. The owned container is stopped in
finally; --rm removes its ephemeral filesystem.
"""

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

ROOT: Path = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "contract_tests")]
# Hermetic bootstrap stubs secrets/settings before importing the actual services.
from test_up_next import service
from app.api.v1.views import add_view, delete_view
from app.models import EpisodeProgress, Media, ShowExclusion, ShowProgress, User, View, Watchlist
from app.schemas.up_next import EpisodeWatched, ShowExclusionRequest
from app.schemas.view import ViewCreate


def run() -> None:
    """Check real DDL, data preservation, idempotency, ownership and rollback."""
    name: str = f"scenario-up-next-test-{uuid4().hex[:12]}"
    subprocess.run([
        "docker", "run", "--detach", "--rm", "--pull", "never", "--name", name,
        "--label", "scenario.test=up-next", "--tmpfs", "/var/lib/postgresql/data",
        "--publish", "127.0.0.1::5432", "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
        "--env", "POSTGRES_DB=scenario_up_next_test", "postgres:16-alpine",
    ], check=True, capture_output=True)
    engine = None
    try:
        details = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
        port: str = details["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        engine = create_engine(f"postgresql+psycopg2://postgres@127.0.0.1:{port}/scenario_up_next_test")
        for attempt in range(60):
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                break
            except OperationalError:
                if attempt == 59:
                    raise
                time.sleep(1)
        with engine.begin() as connection:
            for model in (User, Watchlist, Media, View):
                model.__table__.create(connection)
        owner, other = uuid4(), uuid4()
        payload = dict(tmdb_id=42, media_type="tv", title="Fixture", poster_path="", backdrop_path="", release_date="2020-01-01", release_year="2020", runtime=50, genre_ids=[])
        with Session(engine) as db:
            for identity in (owner, other):
                db.add(User(id=identity, username=f"fixture-{identity}", email=f"{identity}@example.test", hashed_password="not-a-password"))
            db.flush()
            for identity, kind in [(owner, "tv"), (owner, "tv"), (owner, "movie"), (other, "tv")]:
                db.add(View(**{**payload, "media_type": kind}, viewer_id=identity))
            db.commit()
            before = db.execute(select(View.__table__).order_by(View.id)).all()
        spec = importlib.util.spec_from_file_location("progress_migration", ROOT / "app/database/migrations/versions/202610181800_0017_episode_progress.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as connection, patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
        exclusion_spec = importlib.util.spec_from_file_location("exclusion_migration", ROOT / "app/database/migrations/versions/202610181900_0018_show_exclusions.py")
        exclusion_migration = importlib.util.module_from_spec(exclusion_spec)
        exclusion_spec.loader.exec_module(exclusion_migration)
        with engine.begin() as connection, patch.object(exclusion_migration, "op", Operations(MigrationContext.configure(connection))):
            exclusion_migration.upgrade()
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(ShowProgress)) == 2
            assert db.get(ShowProgress, (owner, 42)).caught_up_through == datetime.now(timezone.utc).date()
            assert db.execute(select(View.__table__).order_by(View.id)).all() == before
        season = {"episodes": [{"episode_number": 3, "air_date": "2020-01-01"}]}

        def mark(_: int) -> None:
            """Exercise concurrent duplicate episode writes on independent sessions."""
            with Session(engine) as db:
                service.mark_episode(db, owner, 42, EpisodeWatched(season_number=1, episode_number=3))

        with patch.object(service, "metadata", return_value=season), ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(mark, range(4)))
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(EpisodeProgress)) == 1
            assert db.execute(select(View.__table__).order_by(View.id)).all() == before
            # A brand-new show can start with one episode or one season, without
            # a View or assuming previous seasons watched. Replay stays scoped.
            with patch.object(service, "metadata", return_value={"episodes": [
                {"episode_number": 1, "air_date": "2020-01-01"},
                {"episode_number": 2, "air_date": "2020-01-02"},
                {"episode_number": 3, "air_date": "2999-01-01"},
                {"episode_number": 4, "air_date": None},
            ]}):
                for _ in range(2):
                    service.mark_episode(db, owner, 99, EpisodeWatched(season_number=2, episode_number=1))
                    service.mark_season(db, owner, 99, 2, date(2020, 1, 2))
                assert db.get(ShowProgress, (owner, 99)).caught_up_through == date.min
                rows = db.scalars(select(EpisodeProgress).where(EpisodeProgress.user_id == owner, EpisodeProgress.tmdb_id == 99)).all()
                assert {(row.season_number, row.episode_number) for row in rows} == {(2, 1), (2, 2)}
                assert db.get(ShowProgress, (other, 99)) is None
                assert db.execute(select(View.__table__).order_by(View.id)).all() == before
                add_view(ViewCreate(**{**payload, "tmdb_id": 99}, viewer_id=owner), db.get(User, owner), db)
                db.expire_all()
                assert db.get(ShowProgress, (owner, 99)).caught_up_through == service.utc_today()
                temporary = db.scalar(select(View).where(View.viewer_id == owner, View.tmdb_id == 99))
                delete_view(temporary.id, db.get(User, owner), db)
                db.expire_all()
                assert db.execute(select(View.__table__).order_by(View.id)).all() == before
            cutoff = db.get(ShowProgress, (owner, 42)).caught_up_through
            tomorrow = cutoff + timedelta(days=1)
            queue = Watchlist(title="Bookmarks", type="SYSTEM", author_id=owner)
            db.add(queue)
            db.flush()
            for kind in ("tv", "movie"):
                db.add(Media(watchlist_id=queue.id, type="PENDING", tmdb_id=42, media_type=kind, title="Fixture", poster_path="", backdrop_path="", release_date="2020-01-01", runtime=1, genre_ids=[]))
            db.commit()
            def catalog(path: str, language: str) -> dict:
                """Give the tracked show one newly released episode after its cutoff."""
                if path.startswith("/movie/"):
                    return {"title": "Fixture film", "release_date": (tomorrow + timedelta(days=10)).isoformat()}
                if "append_to_response" in path:
                    return {"season/1": {"episodes": [{"episode_number": 1, "name": "New", "air_date": tomorrow.isoformat()}]}}
                return {"name": "Fixture", "status": "Returning Series", "seasons": [{"season_number": 1}]}
            preference = ShowExclusionRequest(title="Fixture", poster_path="")
            with patch.object(service, "metadata", side_effect=catalog), patch.object(service, "utc_today", return_value=tomorrow):
                assert service.release_feed(db, owner, "en-US").to_watch[0].remaining == 1
                for _ in range(2):
                    service.exclude_show(db, owner, 42, preference)
                service.exclude_show(db, other, 42, preference)
                hidden = service.release_feed(db, owner, "en-US")
                assert hidden.to_watch == [] and len(hidden.excluded) == 1
                assert [item.media_type for item in hidden.upcoming] == ["movie"]
                assert db.get(ShowProgress, (owner, 42)).caught_up_through == cutoff
                assert db.scalar(select(func.count()).select_from(EpisodeProgress)) == 1
                assert db.scalar(select(func.count()).select_from(Media)) == 2
                assert db.execute(select(View.__table__).order_by(View.id)).all() == before
                for _ in range(2):
                    service.restore_show(db, owner, 42)
                assert db.get(ShowExclusion, (other, 42)) is not None
                restored = service.release_feed(db, owner, "en-US")
                assert restored.to_watch[0].episode.episode_number == 1
                assert restored.excluded == []
            service.exclude_show(db, owner, 42, preference)
            # Removing a duplicate retains progress; the final show view clears it.
            ids = db.scalars(select(View.id).where(View.viewer_id == owner, View.media_type == "tv")).all()
            user = db.get(User, owner)
            delete_view(ids[0], user, db)
            assert db.get(ShowProgress, (owner, 42)) is not None
            delete_view(ids[1], user, db)
            db.expire_all()
            assert db.get(ShowProgress, (owner, 42)) is None
            assert db.scalar(select(func.count()).select_from(EpisodeProgress)) == 0
            assert db.get(ShowExclusion, (owner, 42)) is not None
            assert db.get(ShowExclusion, (other, 42)) is not None
            assert db.get(ShowProgress, (other, 42)) is not None
            assert db.scalar(select(func.count()).select_from(View).where(View.viewer_id == owner, View.media_type == "movie")) == 1
            add_view(ViewCreate(**payload, viewer_id=owner), user, db)
            assert db.get(ShowProgress, (owner, 42)) is not None
            with patch.object(service, "metadata", return_value=season):
                service.mark_episode(db, owner, 42, EpisodeWatched(season_number=1, episode_number=3))
            db.delete(user)
            db.commit()
            db.expire_all()
            assert db.get(ShowExclusion, (owner, 42)) is None
            assert db.get(ShowExclusion, (other, 42)) is not None
            assert db.get(ShowProgress, (owner, 42)) is None
            assert db.scalar(select(func.count()).select_from(EpisodeProgress)) == 0
            assert db.get(ShowProgress, (other, 42)) is not None
            snapshot = db.execute(select(View.__table__).order_by(View.id)).all()
        with engine.begin() as connection, patch.object(exclusion_migration, "op", Operations(MigrationContext.configure(connection))):
            exclusion_migration.downgrade()
        with engine.begin() as connection, patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.downgrade()
        with Session(engine) as db:
            assert db.execute(select(View.__table__).order_by(View.id)).all() == snapshot
            assert db.scalar(text("SELECT to_regclass('show_progress')")) is None
            assert db.scalar(text("SELECT to_regclass('episode_progress')")) is None
            assert db.scalar(text("SELECT to_regclass('show_exclusion')")) is None
        print("PostgreSQL 16 rehearsal passed: migrations 0017/0018, preserved history/bookmarks/progress, concurrent episode retries, idempotent exclusions/restores, typed/owner isolation and account cleanup.")
    finally:
        if engine is not None:
            engine.dispose()
        subprocess.run(["docker", "stop", name], check=True, capture_output=True)


if __name__ == "__main__":
    run()
