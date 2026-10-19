"""Rehearse progress against a disposable, loopback-only PostgreSQL 16 container.

Run from the API root: .venv/bin/python scripts/test_up_next_postgres.py
Uses only the already installed postgres:16-alpine image (--pull never), tmpfs,
generated fixture users and mocked TMDB. Never reads application settings or
connects to any configured Scenario database. The owned container is stopped in
finally; --rm removes its ephemeral filesystem.
"""

import importlib.util
import json
from statistics import median
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
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

ROOT: Path = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "contract_tests")]
# Hermetic bootstrap stubs secrets/settings before importing the actual services.
from test_up_next import service
from app.api.v1.views import add_view, delete_view
from app.models import EpisodeProgress, Media, ReleaseCatalog, ShowExclusion, ShowProgress, User, View, Watchlist
from app.services import release_catalog_service as catalogs
from app.services import progress_action_service as actions
from app.schemas.up_next import ProgressActionRequest
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
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO episode_progress (user_id, tmdb_id, season_number, episode_number) VALUES (:owner, 42, 1, 3)"), {"owner": owner})
        catalog_spec = importlib.util.spec_from_file_location("catalog_migration", ROOT / "app/database/migrations/versions/202610190900_0019_release_catalog.py")
        catalog_migration = importlib.util.module_from_spec(catalog_spec)
        catalog_spec.loader.exec_module(catalog_migration)
        with engine.begin() as connection, patch.object(catalog_migration, "op", Operations(MigrationContext.configure(connection))):
            catalog_migration.upgrade()
        action_spec = importlib.util.spec_from_file_location("action_migration", ROOT / "app/database/migrations/versions/202610191000_0020_progress_actions.py")
        action_migration = importlib.util.module_from_spec(action_spec)
        action_spec.loader.exec_module(action_migration)
        with engine.begin() as connection, patch.object(action_migration, "op", Operations(MigrationContext.configure(connection))):
            action_migration.upgrade()
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(ShowProgress)) == 2
            assert db.get(ShowProgress, (owner, 42)).caught_up_through == datetime.now(timezone.utc).date()
            assert db.execute(select(View.__table__).order_by(View.id)).all() == before
            assert db.get(EpisodeProgress, (owner, 42, 1, 3)).watched is True
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
            def catalog(path: str, language: str, session=None) -> dict:
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
        # Actual request-path reads use durable public data, never TMDB. A failed
        # refresh, process restart and a second reader preserve the last snapshot.
        with Session(engine) as db:
            db.execute(delete(ReleaseCatalog))  # Isolate this disposable fixture's lease test.
            catalogs.request_catalog(db, "tv", 42, "en-US")
            db.commit()
            identity = catalogs.claim_catalog(db)
            assert identity[:3] == ("tv", 42, "en-US")
        with Session(engine) as another:
            assert catalogs.claim_catalog(another) is None  # active lease deduplicates workers
        public = {"id": 42, "name": "Fixture", "number_of_episodes": 12, "genres": [], "first_air_date": "2020-01-01", "status": "Returning Series", "seasons": [{"season_number": 1}], "season/1": {"season_number": 1, "episodes": [
            {"episode_number": 1, "name": "One", "air_date": "2020-01-01"},
            {"episode_number": 2, "name": "Two", "air_date": "2020-01-02"},
            {"episode_number": 3, "name": "Future", "air_date": "2999-01-01"},
        ]}}
        with Session(engine) as db:
            catalogs.publish_catalog(db, identity, public)
        with Session(engine) as db, patch.object(catalogs, "TmdbService", side_effect=AssertionError("Request made upstream call")):
            original_history = db.execute(select(View.__table__).order_by(View.id)).all()
            state = service.show_progress(db, other, 42)
            assert state.ready and all(ep.watched for ep in state.episodes)
            service.mark_episode(db, other, 42, EpisodeWatched(season_number=1, episode_number=1, watched=False))
            assert [ep.watched for ep in service.show_progress(db, other, 42).episodes] == [False, True]
            assert service.release_feed(db, other, "en-US").excluded  # independent manual exclusion still wins
            for _ in range(2):
                service.mark_season(db, other, 42, 1, date(2026, 1, 1), False)
            assert not any(ep.watched for ep in service.show_progress(db, other, 42).episodes)
            service.mark_show(db, other, 42, date(2026, 1, 1), True)
            assert all(ep.watched for ep in service.show_progress(db, other, 42).episodes)
            assert db.execute(select(View.__table__).order_by(View.id)).all() == original_history
            # One snapshot is shared between owners, never private progress.
            # Only the explicit show action records/removes whole-show history,
            # atomically with children and without duplicate PUT history rows.
            third = uuid4()
            db.add(User(id=third, username=f"fixture-{third}", email=f"{third}@example.test", hashed_password="not-a-password"))
            db.commit()
            def mark_parent(_: int) -> None:
                """Concurrent explicit parent PUTs must create just one history row."""
                with Session(engine) as writer:
                    service.mark_show(writer, third, 42, date(2026, 1, 1), True, record_history=True)
            with ThreadPoolExecutor(max_workers=4) as workers:
                list(workers.map(mark_parent, range(4)))
            history = db.scalars(select(View).where(View.viewer_id == third)).all()
            assert len(history) == 1 and history[0].runtime == 12
            assert all(ep.watched for ep in service.show_progress(db, third, 42).episodes)
            for _ in range(2):
                service.mark_show(db, third, 42, date(2026, 1, 1), False, record_history=True)
            assert db.scalar(select(func.count()).select_from(View).where(View.viewer_id == third)) == 0
            assert not any(ep.watched for ep in service.show_progress(db, third, 42).episodes)
            assert db.execute(select(View.__table__).order_by(View.id)).all() == original_history
            db.delete(db.get(User, third))
            db.commit()
            state = service.show_progress(db, uuid4(), 42)
            assert not state.tracked and not any(ep.watched for ep in state.episodes)
            catalogs.refresh_owner_catalogs(db, other, "en-US")
            assert catalogs.claim_catalog(db) is None  # completion cooldown
            row = db.get(ReleaseCatalog, ("tv", 42, "en-US"))
            row.updated_at -= timedelta(minutes=2)
            db.commit()
            catalogs.refresh_owner_catalogs(db, other, "en-US")
            identity = catalogs.claim_catalog(db)
            assert identity is not None
            catalogs.refresh_owner_catalogs(db, other, "en-US")
            catalogs.publish_catalog(db, identity, None)
            db.expire_all()
            assert db.get(ReleaseCatalog, ("tv", 42, "en-US")).payload == public
            assert service.show_progress(db, other, 42).ready
            # A newly aired child makes the season incomplete without a progress write.
            row = db.get(ReleaseCatalog, ("tv", 42, "en-US"))
            new_day = service.utc_today() + timedelta(days=1)
            row.payload = {**public, "season/1": {**public["season/1"], "episodes": [*public["season/1"]["episodes"], {"episode_number": 4, "air_date": new_day.isoformat()}]}}
            db.commit()
            with patch.object(service, "utc_today", return_value=new_day):
                assert [ep.watched for ep in service.show_progress(db, other, 42).episodes] == [True, True, False]
        with Session(engine) as db:
            # Cold commands survive independent sessions, opposite taps, partial
            # parents and overlapping scopes. No history until validated/applied.
            cold = 88
            frozen = date(2026, 1, 1)
            first = ProgressActionRequest(id=uuid4(), through=frozen, watched=True)
            pending = actions.submit_action(db, other, cold, first)
            assert pending.status == "pending"
            assert actions.submit_action(db, other, cold, first).id == first.id
            for target in [
                dict(season_number=1, watched=False),
                dict(season_number=1, episode_number=1, watched=True),
                dict(season_number=1, episode_number=999, watched=True),
            ]:
                assert actions.submit_action(db, other, cold, ProgressActionRequest(id=uuid4(), through=frozen, **target)).status == "pending"
            assert len(actions.action_states(db, other, cold)) == 4
            assert actions.action_states(db, uuid4(), cold) == []
            assert db.get(ReleaseCatalog, ("tv", cold, "en-US")).priority == 10
            row = db.get(ReleaseCatalog, ("tv", cold, "en-US"))
            row.payload = {**public, "id": cold}
            db.commit()
        with Session(engine) as db:
            actions.drain_ready_actions(db)
            assert [item.status for item in actions.action_states(db, other, cold)] == ["applied", "applied", "applied", "failed"]
            assert [ep.watched for ep in service.show_progress(db, other, cold).episodes] == [True, False]
            # The original show tap creates only one history record. Child changes
            # do not touch it; a later show unwatch removes it and wins all children.
            assert db.scalar(select(func.count()).select_from(View).where(View.viewer_id == other, View.tmdb_id == cold)) == 1
            undo = ProgressActionRequest(id=uuid4(), through=frozen, watched=False)
            assert actions.submit_action(db, other, cold, undo).status == "applied"
            assert not any(ep.watched for ep in service.show_progress(db, other, cold).episodes)
            assert db.scalar(select(func.count()).select_from(View).where(View.viewer_id == other, View.tmdb_id == cold)) == 0
            # No action queued on Jan 1 may mark a Jan 2 release while waiting.
            row = db.get(ReleaseCatalog, ("tv", cold, "en-US"))
            row.payload = {**public, "id": cold, "season/1": {"season_number": 1, "episodes": [{"episode_number": 1, "air_date": "2026-01-02"}]}}
            db.commit()
            too_early = ProgressActionRequest(id=uuid4(), season_number=1, episode_number=1, through=frozen, watched=True)
            assert actions.submit_action(db, other, cold, too_early).status == "failed"
            wrong_season = ProgressActionRequest(id=uuid4(), season_number=999, through=frozen, watched=True)
            assert actions.submit_action(db, other, cold, wrong_season).status == "failed"
            try:
                actions.submit_action(db, other, cold, first.model_copy(update={"watched": False}))
                raise AssertionError("Conflicting action identity was accepted")
            except Exception as error:
                assert getattr(error, "status_code", None) == 409
                db.rollback()
        same_intent = ProgressActionRequest(id=uuid4(), season_number=1, episode_number=1, through=date(2026, 1, 2), watched=True)
        def submit_concurrently(_: int) -> None:
            """A single operation identity remains unique across independent request sessions."""
            with Session(engine) as writer:
                assert actions.submit_action(writer, other, cold, same_intent).status == "applied"
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(submit_concurrently, range(4)))
        with Session(engine) as db:
            assert len([item for item in actions.action_states(db, other, cold) if item.id == same_intent.id]) == 1
            # Later legacy history actions cancel older pending choices, so a
            # worker cannot resurrect a deliberately removed viewing record.
            cancellation_show = 99
            waiting = ProgressActionRequest(id=uuid4(), through=frozen, watched=True)
            assert actions.submit_action(db, other, cancellation_show, waiting).status == "pending"
            add_view(ViewCreate(**{**payload, "viewer_id": other, "tmdb_id": cancellation_show}), db.get(User, other), db)
            assert actions.action_states(db, other, cancellation_show)[0].status == "cancelled"
            waiting = waiting.model_copy(update={"id": uuid4(), "season_number": 1, "episode_number": 1})
            assert actions.submit_action(db, other, cancellation_show, waiting).status == "pending"
            record_id = db.scalar(select(View.id).where(View.viewer_id == other, View.tmdb_id == cancellation_show))
            delete_view(record_id, db.get(User, other), db)
            assert all(item.status == "cancelled" for item in actions.action_states(db, other, cancellation_show))
            row = db.get(ReleaseCatalog, ("tv", cancellation_show, "en-US"))
            row.payload = {**public, "id": cancellation_show}
            db.commit()
            actions.drain_ready_actions(db)
            assert db.get(ShowProgress, (other, cancellation_show)) is None
            assert db.scalar(select(func.count()).select_from(View).where(View.viewer_id == other, View.tmdb_id == cancellation_show)) == 0
        # Reproducible local request-path measurement, not a phone/network claim.
        bench = uuid4()
        verbose = {**public, "season/1": {"season_number": 1, "episodes": [
            {"episode_number": n, "air_date": "2020-01-01", "name": f"Episode {n}", "overview": "Synopsis " * 120, "crew": [{"id": i, "name": f"Crew {i}"} for i in range(12)]}
            for n in range(1, 301)
        ]}}
        compact = catalogs.compact_catalog(verbose)
        with Session(engine) as db:
            db.add(User(id=bench, username=f"bench-{bench}", email=f"{bench}@example.test", hashed_password="not-a-password"))
            db.commit()
            for number in range(1000, 1060):
                db.add(ShowProgress(user_id=bench, tmdb_id=number, caught_up_through=date.min))
                db.add(ReleaseCatalog(media_type="tv", tmdb_id=number, language="en-US", payload=verbose, next_refresh_at=datetime.now(timezone.utc) + timedelta(hours=6)))
            db.commit()
        timings = {}
        with patch.object(catalogs, "TmdbService", side_effect=AssertionError("Benchmark made upstream call")):
            for variant, payload in [("full_snapshot", verbose), ("compact_snapshot", compact)]:
                with Session(engine) as db:
                    for row in db.scalars(select(ReleaseCatalog).where(ReleaseCatalog.tmdb_id >= 1000)).all():
                        row.payload = payload
                    db.commit()
                samples = []
                for _ in range(5):
                    with Session(engine) as db:
                        start = time.perf_counter()
                        feed = service.release_feed(db, bench, "en-US")
                        samples.append(round((time.perf_counter() - start) * 1000, 1))
                        assert len(feed.to_watch) == 60
                timings[variant] = {"first_read_ms": samples[0], "warm_median_ms": median(samples[1:]), "snapshot_bytes_per_show": len(json.dumps(payload))}
        print("Local PostgreSQL benchmark (60 shows × 300 episodes; no upstream calls): " + json.dumps(timings))
        with Session(engine) as db:
            db.delete(db.get(User, bench))
            db.commit()
        with engine.begin() as connection, patch.object(action_migration, "op", Operations(MigrationContext.configure(connection))):
            action_migration.downgrade()
        with engine.begin() as connection, patch.object(catalog_migration, "op", Operations(MigrationContext.configure(connection))):
            catalog_migration.downgrade()
        with engine.begin() as connection, patch.object(exclusion_migration, "op", Operations(MigrationContext.configure(connection))):
            exclusion_migration.downgrade()
        with engine.begin() as connection, patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.downgrade()
        with Session(engine) as db:
            assert db.execute(select(View.__table__).order_by(View.id)).all() == snapshot
            assert db.scalar(text("SELECT to_regclass('show_progress')")) is None
            assert db.scalar(text("SELECT to_regclass('episode_progress')")) is None
            assert db.scalar(text("SELECT to_regclass('show_exclusion')")) is None
        print("PostgreSQL 16 rehearsal passed: migrations 0017–0020, preserved history, reversible overrides, durable catalogues, prioritized worker leases, ordered cold intents, failure receipts, cutoff and owner isolation.")
    finally:
        if engine is not None:
            engine.dispose()
        subprocess.run(["docker", "stop", name], check=True, capture_output=True)


if __name__ == "__main__":
    run()
