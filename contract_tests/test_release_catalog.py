"""Hermetic catalogue, reversible progress and no-upstream-request contracts."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
import sys
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from test_up_next import service
from app.services import release_catalog_service as catalog
from app.schemas.up_next import EpisodeWatched


class StoredCatalogContracts(TestCase):
    """Page reads never depend on upstream availability or rebuild catalogues."""

    def test_warm_reads_use_last_complete_payload_without_network_or_jobs(self) -> None:
        """Even an expired snapshot remains immediately readable during refresh."""
        db = MagicMock()
        db.info = {}
        season = {"season_number": 1, "episodes": []}
        payload = {"id": 42, "seasons": [{"season_number": 1}], "season/1": season}
        db.get.return_value = SimpleNamespace(payload=payload, failed_at=datetime.now(timezone.utc))
        with patch.object(catalog, "TmdbService") as upstream:
            self.assertEqual(service.metadata("/tv/42", "en-US", db), payload)
            self.assertEqual(service.metadata("/tv/42/season/1", "en-US", db), season)
            self.assertEqual(service.regular_episodes(payload, 42, "en-US", db), [])
        upstream.assert_not_called()
        db.execute.assert_not_called()
        self.assertEqual(db.get.call_count, 1)

    def test_cold_read_enqueues_once_and_never_fetches_inline(self) -> None:
        """A first encounter creates only one shared public identity."""
        db = MagicMock()
        db.info = {}
        db.get.side_effect = [None, SimpleNamespace(payload=None, failed_at=None)]
        with patch.object(catalog, "TmdbService") as upstream:
            for _ in range(2):
                with self.assertRaises(catalog.CatalogPending):
                    service.metadata("/tv/42", "fr-FR", db)
        upstream.assert_not_called()
        self.assertEqual(db.execute.call_count, 1)
        sql = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertIn("DO UPDATE SET priority", str(sql))
        self.assertIn("WHERE release_catalog.payload IS NULL", str(sql))
        self.assertEqual(sql.params["language"], "fr-FR")
        self.assertNotIn("user_id", sql.params)

    def test_worker_requires_complete_identity_checked_catalogue(self) -> None:
        """Partial/duplicate season data must never replace a last good snapshot."""
        root = {"id": 42, "seasons": [{"season_number": 0}, {"season_number": 1}]}
        valid = {"id": 42, "season/1": {"season_number": 1, "episodes": [{"episode_number": 1}]}}
        with patch.object(catalog, "TmdbService") as client:
            client.return_value.get_release_details.side_effect = [root, valid]
            data = catalog.fetch_catalog("tv", 42, "en-US")
            self.assertIn("season/1", data)
            self.assertNotIn("season/0", data)
            client.return_value.get_release_details.side_effect = [{**root}, {}]
            with self.assertRaises(RuntimeError):
                catalog.fetch_catalog("tv", 42, "en-US")
            client.return_value.get_release_details.side_effect = [{"id": 999}]
            with self.assertRaises(RuntimeError):
                catalog.fetch_catalog("movie", 42, "en-US")

    def test_compact_catalogue_preserves_release_semantics_without_heavy_fields(self) -> None:
        """Workers strip irrelevant episode metadata before persisting/request deserialization."""
        episode = {"episode_number": 1, "air_date": "2020-01-01", "name": "One", "overview": "Long", "crew": [{"id": 1}]}
        raw = {"id": 42, "name": "Show", "number_of_episodes": 12, "seasons": [{"season_number": 0}, {"season_number": 1}], "season/1": {"season_number": 1, "episodes": [episode]}, "credits": {"cast": []}}
        compact = catalog.compact_catalog(raw)
        self.assertNotIn("credits", compact)
        self.assertEqual(compact["number_of_episodes"], 12)
        self.assertEqual(compact["seasons"], [{"season_number": 1}])
        self.assertEqual(compact["season/1"]["episodes"], [{"episode_number": 1, "air_date": "2020-01-01", "name": "One"}])
        self.assertIn("crew", raw["season/1"]["episodes"][0])

    def test_claim_uses_skip_locked_and_publish_fences_abandoned_worker(self) -> None:
        """Lease coordination is database-backed and survives process restarts."""
        db = MagicMock()
        db.scalar.return_value = None
        self.assertIsNone(catalog.claim_catalog(db))
        sql = db.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertIn("FOR UPDATE SKIP LOCKED", str(sql))
        self.assertIn("ORDER BY release_catalog.priority DESC", str(sql))
        catalog.publish_catalog(db, ("tv", 42, "en-US", datetime.now(timezone.utc)), {"id": 42})
        db.commit.assert_not_called()
        self.assertEqual(db.rollback.call_count, 2)

    def test_failed_refresh_retains_payload_and_sets_backoff(self) -> None:
        """A failed external call never clears usable public data."""
        now = datetime.now(timezone.utc)
        row = SimpleNamespace(payload={"id": 42}, updated_at=now - timedelta(days=1), leased_until=now)
        db = MagicMock()
        db.scalar.return_value = row
        catalog.publish_catalog(db, ("tv", 42, "en-US", now), None)
        self.assertEqual(row.payload, {"id": 42})
        self.assertIsNotNone(row.failed_at)
        self.assertGreater(row.next_refresh_at, now)
        self.assertIsNone(row.leased_until)

    def test_worker_closes_claim_session_before_external_fetch(self) -> None:
        """Worker network calls cannot occupy a request's session or DB connection."""
        with patch.object(sys.modules["app.database.session"], "SessionLocal", MagicMock(), create=True):
            from app.services import release_catalog_scheduler as worker
        identity = ("tv", 42, "en-US", datetime.now(timezone.utc))
        events = []
        factory = MagicMock()
        factory.return_value.__exit__.side_effect = lambda *args: events.append("closed")
        with patch.object(worker, "SessionLocal", factory), patch.object(worker, "seed_catalogs"), patch.object(worker, "claim_catalog", return_value=identity), patch.object(worker, "publish_catalog") as publish, patch.object(worker, "fetch_catalog", side_effect=lambda *args: events.append("fetch") or {"id": 42}):
            self.assertTrue(worker.ReleaseCatalogScheduler()._tick())
        self.assertEqual(events, ["closed", "fetch", "closed"])
        self.assertEqual(publish.call_args.args[-1], {"id": 42})


class ReversibleProgressContracts(TestCase):
    """Explicit unwatched state wins over historical cutoffs without changing history."""

    def test_cutoff_episode_can_be_unwatched_then_watched_idempotently(self) -> None:
        db = MagicMock()
        owner = uuid4()
        for watched in (False, False, True, True):
            with patch.object(service, "metadata", return_value={"episodes": [{"episode_number": 1, "air_date": "2020-01-01"}]}):
                service.mark_episode(db, owner, 42, EpisodeWatched(season_number=1, episode_number=1, watched=watched))
            sql = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
            self.assertEqual(sql.params["watched"], watched)
            self.assertIn("DO UPDATE SET watched = excluded.watched", str(sql))
            self.assertEqual(sql.params["user_id"], owner)
        db.add.assert_not_called()

    def test_negative_override_reopens_a_finished_show_even_before_cutoff(self) -> None:
        episode = service.EpisodeRef(season_number=1, episode_number=1, name="One", air_date=date(2020, 1, 1))
        with patch.object(service, "metadata", return_value={"status": "Ended"}), patch.object(service, "regular_episodes", return_value=[episode]):
            ready, _, completed = service.build_title(("tv", 42, date(2026, 1, 1), frozenset(), frozenset({(1, 1)})), "en-US", date(2026, 1, 1))
        self.assertEqual(ready.remaining, 1)
        self.assertIsNone(completed)

    def test_show_bulk_respects_snapshot_date_and_does_not_touch_history(self) -> None:
        db = MagicMock()
        episodes = [service.EpisodeRef(season_number=1, episode_number=number, name="E", air_date=day) for number, day in [(1, date(2020, 1, 1)), (2, date(2999, 1, 1))]]
        with patch.object(service, "metadata", return_value={}), patch.object(service, "regular_episodes", return_value=episodes):
            service.mark_show(db, uuid4(), 42, date(2020, 1, 1), False)
        sql = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertFalse(sql.params["watched_m0"])
        self.assertNotIn("episode_number_m1", sql.params)
        db.add.assert_not_called()

    def test_explicit_show_history_uses_stored_episode_count_and_owner_scope(self) -> None:
        """Only the explicit show action records history, using canonical stored metadata."""
        db = MagicMock()
        db.scalar.side_effect = [SimpleNamespace(), None]
        owner = uuid4()
        episode = service.EpisodeRef(season_number=1, episode_number=1, name="One", air_date=date(2020, 1, 1))
        details = {"name": "Show", "number_of_episodes": 12, "first_air_date": "2020-01-01", "genres": [{"id": 18}]}
        with patch.object(service, "metadata", return_value=details), patch.object(service, "regular_episodes", return_value=[episode]):
            service.mark_show(db, owner, 42, date(2026, 1, 1), True, record_history=True)
        history = db.add.call_args.args[0]
        self.assertEqual(history.viewer_id, owner)
        self.assertEqual(history.media_type, "tv")
        self.assertEqual(history.runtime, 12)
        self.assertEqual(history.genre_ids, [0, 18])
        self.assertIsNotNone(history.recorded_at)
        self.assertEqual(db.commit.call_count, 1)
        lock = db.scalar.call_args_list[0].args[0].compile(dialect=postgresql.dialect())
        self.assertIn("FOR UPDATE", str(lock))

    def test_explicit_show_unwatch_deletes_only_owned_tv_history_not_progress(self) -> None:
        """A show unwatch keeps tracking and negative children, unlike history cascade deletion."""
        db = MagicMock()
        owner = uuid4()
        episode = service.EpisodeRef(season_number=1, episode_number=1, name="One", air_date=date(2020, 1, 1))
        with patch.object(service, "metadata", return_value={}), patch.object(service, "regular_episodes", return_value=[episode]):
            service.mark_show(db, owner, 42, date(2026, 1, 1), False, record_history=True)
        deletion = db.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect())
        self.assertIn("DELETE FROM view_model", str(deletion))
        self.assertEqual(deletion.params["viewer_id_1"], owner)
        self.assertEqual(deletion.params["media_type_1"], "tv")
        self.assertFalse(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()).params["watched_m0"])
