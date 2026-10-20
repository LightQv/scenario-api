"""Hermetic release/progress contracts; no settings, TMDB or database connection."""

import importlib.util
import io
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

# Reuse the existing hermetic external-boundary bootstrap, never real settings.
from test_insights import stub

with patch.dict(sys.modules, {"app.core.settings": stub("app.core.settings", settings=SimpleNamespace(TMDB_API_TOKEN="fixture"))}):
    from app.services import up_next_service as service
    from app.api.v1.up_next import router

from app.api.dependencies import get_current_user, get_database
from app.api.v1.views import add_view, delete_view
from app.schemas.up_next import EpisodeWatched
from app.schemas.view import ViewCreate
from app.services.viewing_activity_service import OwnerActivity, watched_regular_count


class ReleaseContracts(TestCase):
    """Calculate progress using frozen cutoffs, never imported viewing timestamps."""

    def setUp(self) -> None:
        """Prepare non-contiguous episodes, future releases, specials and unknown dates."""
        self.today = date(2026, 10, 18)
        self.details = {
            "name": "A show", "poster_path": "/poster.jpg", "status": "Returning Series",
            "next_episode_to_air": {"season_number": 0, "episode_number": 5, "air_date": "2026-10-19"},
            "seasons": [{"season_number": 0}, {"season_number": 1}, {"season_number": 2}],
        }
        self.episodes = {
            "/tv/42": self.details,
            "/tv/42/season/1": {"episodes": [
                {"episode_number": 1, "air_date": "2026-09-01", "name": "One"},
                {"episode_number": 3, "air_date": "2026-10-17", "name": "Three"},
                {"episode_number": 5, "air_date": "2026-10-18", "name": "Five"},
                {"episode_number": 6, "air_date": None, "name": "Unknown"},
            ]},
            "/tv/42/season/2": {"episodes": [
                {"episode_number": 1, "air_date": "2026-10-23", "name": "Premiere"},
                {"episode_number": 2, "air_date": "2026-10-30", "name": "Later"},
            ]},
            "/movie/42": {"title": "A film", "release_date": "2026-11-06"},
        }
        def catalog(path: str, language: str, db=None) -> dict:
            """Emulate TMDB's appended-season response, not a custom API shape."""
            if "?append_to_response=" in path:
                root, appended = path.split("?append_to_response=")
                return {season: self.episodes[f"{root}/{season}"] for season in appended.split(",")}
            return self.episodes[path]
        self.metadata = patch.object(service, "metadata", side_effect=catalog).start()
        patch.object(service, "preload_catalogs").start()
        self.addCleanup(patch.stopall)

    def build(self, cutoff: date | None, watched: frozenset[tuple[int, int]] = frozenset()) -> tuple:
        """Calculate one fixture title with no external requests."""
        return service.build_title(("tv", 42, cutoff, watched), "en-US", self.today)

    def test_cutoff_does_not_slide_and_specials_are_never_requested(self) -> None:
        """New episodes remain missing across reads; TMDB's special next pointer is ignored."""
        for _ in range(2):
            ready, upcoming, caught = self.build(date(2026, 10, 1))
            self.assertEqual((ready.episode.season_number, ready.episode.episode_number), (1, 3))
            self.assertEqual(ready.remaining, 2)
            self.assertEqual(ready.watched_episodes, 1)
            self.assertEqual(upcoming.episode.season_number, 2)
            self.assertIsNone(caught)
        self.assertFalse(any("season/0" in call.args[0] for call in self.metadata.call_args_list))
        self.assertTrue(any("append_to_response=season/1,season/2" in call.args[0] for call in self.metadata.call_args_list))

    def test_explicit_progress_handles_holes_without_assuming_contiguous_numbers(self) -> None:
        """Only the explicitly marked episode disappears, not its neighbors."""
        ready, upcoming, caught = self.build(date(2026, 10, 1), frozenset({(1, 3)}))
        self.assertEqual(ready.episode.episode_number, 5)
        self.assertEqual(ready.remaining, 1)
        self.assertEqual(ready.watched_episodes, 2)
        self.assertIsNotNone(upcoming)

    def test_conversion_marks_released_only_and_unknown_dates_do_not_become_released(self) -> None:
        """The conversion-day assumption excludes future and undated episodes."""
        ready, upcoming, caught = self.build(self.today)
        self.assertIsNone(ready)
        self.assertEqual(caught.aired_episodes, 3)
        self.assertEqual(upcoming.episode.episode_number, 1)
        ready, _, _ = service.build_title(("tv", 42, self.today, frozenset()), "en-US", date(2026, 10, 24))
        self.assertEqual((ready.episode.season_number, ready.episode.episode_number), (2, 1))

    def test_bookmark_has_ready_and_upcoming_but_never_assumed_progress(self) -> None:
        """Bookmarking a series is not evidence of watched episodes."""
        ready, upcoming, caught = self.build(None)
        self.assertEqual(ready.episode.episode_number, 1)
        self.assertEqual(ready.watched_episodes, 0)
        self.assertEqual(ready.remaining, 3)
        self.assertIsNone(caught)
        self.assertTrue(upcoming.tracked)

    def test_missing_season_catalog_is_unavailable_not_caught_up(self) -> None:
        """Partial TMDB append success never manufactures a completed show."""
        with patch.object(service, "metadata", side_effect=[self.details, {}]):
            self.assertIsNone(service.safe_title(("tv", 42, self.today, frozenset()), "en-US", self.today))

    def test_large_catalog_is_batched_below_tmdb_append_limit(self) -> None:
        """Long-running shows do not need one HTTP request per season."""
        details = {"seasons": [{"season_number": number} for number in range(32)]}
        def catalog(path: str, language: str, db=None) -> dict:
            """Return all requested season objects in one response."""
            seasons = path.split("?append_to_response=")[1].split(",")
            self.assertLessEqual(len(seasons), 15)
            self.assertNotIn("season/0", seasons)
            return {season: {"episodes": []} for season in seasons}
        with patch.object(service, "metadata", side_effect=catalog) as request:
            self.assertEqual(service.regular_episodes(details, 42, "en-US"), [])
            self.assertEqual(request.call_count, 3)

    def test_movies_move_from_upcoming_to_ready_on_release(self) -> None:
        """A bookmarked unwatched movie stays actionable after release day."""
        _, upcoming, _ = service.build_title(("movie", 42, None, frozenset()), "fr-FR", self.today)
        self.assertEqual(upcoming.date, date(2026, 11, 6))
        ready, upcoming, _ = service.build_title(("movie", 42, None, frozenset()), "fr-FR", date(2026, 11, 6))
        self.assertIsNone(upcoming)
        self.assertEqual(ready.media_type, "movie")
        self.assertIsNone(ready.episode)

    def test_feed_owner_predicates_bookmark_scope_deduplication_and_partial_failure(self) -> None:
        """No themed-list source, ID collision, private cache or write on a feed read."""
        owner = uuid4()
        db = MagicMock()
        db.scalars.return_value.all.side_effect = [
            [SimpleNamespace(tmdb_id=42, caught_up_through=date(2026, 10, 1))], [],
            [SimpleNamespace(tmdb_id=42, media_type="tv"), SimpleNamespace(tmdb_id=42, media_type="movie"), SimpleNamespace(tmdb_id=99, media_type="tv")],
            [], [],
        ]
        db.scalar.return_value = None
        with patch.object(service, "utc_today", return_value=self.today):
            feed = service.release_feed(db, owner, "fr-FR")
        self.assertEqual(len(feed.to_watch), 1)
        self.assertEqual(len(feed.upcoming), 2)
        self.assertEqual(feed.unavailable, 1)
        self.assertEqual(feed.user_id, owner)
        statements = [call.args[0].compile(dialect=postgresql.dialect()) for call in db.scalars.call_args_list]
        self.assertEqual(statements[0].params["user_id_1"], owner)
        self.assertEqual(statements[1].params["user_id_1"], owner)
        self.assertEqual(statements[2].params["author_id_1"], owner)
        self.assertEqual(statements[2].params["type_1"], "SYSTEM")
        self.assertEqual(statements[2].params["type_2"], "PENDING")
        db.commit.assert_not_called()
        db.execute.assert_not_called()

    def test_completed_shows_hide_only_after_all_aired_regular_episodes_are_watched(self) -> None:
        """Terminal status never hides remaining released episodes or announces completion early."""
        for status in ("Ended", "Canceled"):
            self.details["status"] = status
            ready, upcoming, caught = self.build(self.today)
            self.assertIsNone(ready)
            self.assertEqual(caught.status, status)
            self.assertEqual(caught.remaining, 0)
            self.assertIsNotNone(upcoming)  # TMDB can mark Ended before an announced finale airs.
            ready, _, caught = self.build(date(2026, 10, 1))
            self.assertEqual(ready.remaining, 2)
            self.assertIsNone(caught)

    def test_exclusions_override_bookmarks_and_progress_but_not_same_id_movies(self) -> None:
        """Read the owner's exclusion snapshot without requesting excluded-show metadata."""
        owner = uuid4()
        db = MagicMock()
        db.scalars.return_value.all.side_effect = [
            [SimpleNamespace(tmdb_id=42, caught_up_through=self.today)], [],
            [SimpleNamespace(tmdb_id=42, media_type="tv"), SimpleNamespace(tmdb_id=42, media_type="movie")],
            [],
            [SimpleNamespace(tmdb_id=42, title="Paused show", poster_path="/poster.jpg")],
        ]
        db.scalar.return_value = None
        with patch.object(service, "utc_today", return_value=self.today):
            feed = service.release_feed(db, owner, "en-US")
        self.assertEqual(feed.to_watch, [])
        self.assertEqual(feed.caught_up, [])
        self.assertEqual([item.media_type for item in feed.upcoming], ["movie"])
        self.assertEqual(feed.excluded[0].title, "Paused show")
        self.assertFalse(any(call.args[0].startswith("/tv/") for call in self.metadata.call_args_list))
        sql = db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertEqual(sql.params["user_id_1"], owner)

    def test_finished_listing_is_read_only_and_separate_from_caught_up(self) -> None:
        """Ended caught-up titles remain consultable, with future releases retained."""
        self.details["status"] = "Ended"
        db = MagicMock()
        db.scalars.return_value.all.side_effect = [[SimpleNamespace(tmdb_id=42, caught_up_through=self.today)], [], [], [], []]
        db.scalar.return_value = None
        with patch.object(service, "utc_today", return_value=self.today):
            feed = service.release_feed(db, uuid4(), "en-US")
        self.assertEqual(feed.caught_up, [])
        self.assertEqual([entry.tmdb_id for entry in feed.finished], [42])
        self.assertEqual(len(feed.upcoming), 1)
        db.execute.assert_not_called()
        db.commit.assert_not_called()

    def test_only_bookmarks_history_or_effective_watched_episodes_keep_next_active(self) -> None:
        """Unwatch-all stops following unless another visible source remains."""
        owner = uuid4()
        db = MagicMock()
        db.scalars.return_value.all.return_value = []  # no exclusions
        db.scalar.return_value = None
        for cutoff in (date.min, self.today):
            overrides = {(1, 1): False, (1, 3): False, (1, 5): False}
            activity = OwnerActivity({42: cutoff}, {42: overrides}, set(), set())
            with patch.object(service, "owner_activity", return_value=activity), patch.object(service, "utc_today", return_value=self.today):
                feed = service.release_feed(db, owner, "en-US")
                self.assertEqual((feed.to_watch, feed.upcoming, feed.caught_up), ([], [], []))
                activity.bookmarks.add(("tv", 42))
                feed = service.release_feed(db, owner, "en-US")
                self.assertEqual(feed.to_watch[0].episode.episode_number, 1)
                self.assertEqual(feed.to_watch[0].watched_episodes, 0)
                activity.bookmarks.clear()
                activity.overrides[42][(1, 3)] = True
                feed = service.release_feed(db, owner, "en-US")
                self.assertEqual(feed.to_watch[0].watched_episodes, 1)
                self.assertEqual(feed.to_watch[0].episode.episode_number, 1)
        db.commit.assert_not_called()

    def test_watched_movie_bookmark_does_not_leak_into_either_section(self) -> None:
        """Movie and TV identities remain independent for shared numerical IDs."""
        activity = OwnerActivity({}, {}, {("movie", 42), ("tv", 42)}, {("movie", 42)})
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        db.scalar.return_value = None
        with patch.object(service, "owner_activity", return_value=activity), patch.object(service, "utc_today", return_value=self.today):
            feed = service.release_feed(db, uuid4(), "en-US")
        self.assertEqual([entry.media_type for entry in feed.to_watch], ["tv"])
        self.assertEqual([entry.media_type for entry in feed.upcoming], ["tv"])

    def test_old_clients_keep_the_episode_only_contract_until_app_activation(self) -> None:
        """An API-first rollout must not send movie cards to an older PWA parser."""
        self.episodes["/movie/42"]["release_date"] = self.today.isoformat()
        activity = OwnerActivity({}, {}, {("movie", 42), ("tv", 42)}, set())
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        db.scalar.return_value = None
        with patch.object(service, "owner_activity", return_value=activity), patch.object(service, "utc_today", return_value=self.today):
            legacy = service.release_feed(db, uuid4(), "en-US", activity_model=False)
            self.assertEqual(legacy.to_watch, [])
            self.assertEqual([entry.media_type for entry in legacy.upcoming], ["tv"])
            self.assertFalse(legacy.upcoming[0].tracked)
            updated = service.release_feed(db, uuid4(), "en-US")
            self.assertEqual({entry.media_type for entry in updated.to_watch}, {"tv", "movie"})

    def test_viewed_projects_partial_activity_without_history_or_dates(self) -> None:
        """Exclusions affect Next only; bookmark-only and false-only shows are not Viewed."""
        owner = uuid4()
        db = MagicMock()
        db.scalar.return_value = None
        activity = OwnerActivity({42: date.min}, {42: {(1, 3): True}}, set(), set())
        with patch.object(service, "owner_activity", return_value=activity), patch.object(service, "utc_today", return_value=self.today):
            result = service.viewed_shows(db, owner, "en-US")
            self.assertEqual(result.user_id, owner)
            self.assertEqual(len(result.shows), 1)
            self.assertEqual((result.shows[0].watched_episodes, result.shows[0].aired_episodes, result.shows[0].status), (1, 3, "in_progress"))
            self.assertNotIn("recorded_at", result.shows[0].model_dump())
            self.assertNotIn("runtime", result.shows[0].model_dump())
            activity.overrides[42][(1, 3)] = False
            activity.bookmarks.add(("tv", 42))
            self.assertEqual(service.viewed_shows(db, owner, "en-US").shows, [])
            activity.cutoffs[42] = self.today
            self.assertEqual(service.viewed_shows(db, owner, "en-US").shows[0].status, "in_progress")
            activity.overrides.clear()
            self.assertEqual(service.viewed_shows(db, owner, "en-US").shows[0].status, "caught_up")
            self.details["status"] = "Ended"
            self.assertEqual(service.viewed_shows(db, owner, "en-US").shows[0].status, "caught_up")  # announced future episodes
            self.episodes["/tv/42/season/2"] = {"episodes": []}
            self.assertEqual(service.viewed_shows(db, owner, "en-US").shows[0].status, "completed")
        db.commit.assert_not_called()
        db.execute.assert_not_called()

    def test_notification_activity_count_matches_next_with_negative_overrides(self) -> None:
        """Unknown/future/special children never establish positive viewing activity."""
        payload = {**self.details, "season/1": self.episodes["/tv/42/season/1"], "season/2": self.episodes["/tv/42/season/2"],
                   "season/0": {"episodes": [{"episode_number": 1, "air_date": "2020-01-01"}]}}
        self.assertEqual(watched_regular_count(payload, date.min, {(1, 3): True, (2, 1): True}, self.today), 1)
        self.assertEqual(watched_regular_count(payload, self.today, {(1, 1): False, (1, 3): False, (1, 5): False}, self.today), 0)


class ProgressApiContracts(TestCase):
    """Verify authenticated ownership, validation and replay-safe writes."""

    def setUp(self) -> None:
        """Mount real routes with trusted cookie-owner and database fixtures."""
        self.owner = uuid4()
        self.db = MagicMock()
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/v1/up-next")
        self.app.dependency_overrides[get_database] = lambda: self.db
        self.client = TestClient(self.app)

    def authenticate(self) -> None:
        """Use the actual authentication boundary, not caller-controlled identity."""
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=self.owner)
        self.client.headers["X-Scenario-Owner"] = str(self.owner)

    def test_anonymous_cannot_read_or_write(self) -> None:
        """Private progress is not public viewing history."""
        self.assertEqual(self.client.get("/api/v1/up-next").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/up-next/viewed").status_code, 403)
        self.assertEqual(self.client.put("/api/v1/up-next/shows/42/episodes", json={"season_number": 1, "episode_number": 1}).status_code, 403)
        self.db.scalars.assert_not_called()
        self.db.execute.assert_not_called()

    def test_read_is_no_store_and_cannot_forge_an_owner(self) -> None:
        """Server-derived owner is echoed so a mismatched remembered profile can reject it."""
        self.authenticate()
        self.db.scalars.return_value.all.return_value = []
        response = self.client.get(f"/api/v1/up-next?user_id={uuid4()}&language=fr-FR")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], str(self.owner))
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        response = self.client.get(f"/api/v1/up-next/viewed?user_id={uuid4()}&language=fr-FR")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], str(self.owner))
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.db.commit.assert_not_called()

    def test_invalid_locale_specials_unknown_owner_fields_and_ids_rejected(self) -> None:
        """Neither arbitrary TMDB paths nor specials can enter mutation validation."""
        self.authenticate()
        self.assertEqual(self.client.get("/api/v1/up-next?language=bad").status_code, 422)
        for payload in [{"season_number": 0, "episode_number": 1}, {"season_number": 1, "episode_number": 0}, {"season_number": True, "episode_number": 1}, {"season_number": 1, "episode_number": 1, "user_id": str(uuid4())}]:
            self.assertEqual(self.client.put("/api/v1/up-next/shows/42/episodes", json=payload).status_code, 422)
        self.assertEqual(self.client.put("/api/v1/up-next/shows/0/episodes", json={"season_number": 1, "episode_number": 1}).status_code, 422)
        self.db.execute.assert_not_called()

    def test_missing_tracking_starts_only_this_owners_show(self) -> None:
        """A first episode creates an empty owner-bound baseline, never neighbors."""
        self.authenticate()
        self.db.scalar.return_value = None
        with patch.object(service, "metadata", return_value={"episodes": [{"episode_number": 1, "air_date": "2020-01-01"}]}):
            response = self.client.put("/api/v1/up-next/shows/42/episodes", json={"season_number": 1, "episode_number": 1})
        self.assertEqual(response.status_code, 204)
        statement = self.db.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect())
        self.assertEqual(statement.params["user_id"], self.owner)
        self.assertEqual(statement.params["tmdb_id"], 42)
        self.assertEqual(statement.params["caught_up_through"], date.min)

    def test_cookie_owner_change_or_missing_guard_cannot_mutate_from_stale_feed(self) -> None:
        """An authenticated but different cookie owner cannot act on the old user's card."""
        self.authenticate()
        for header in [str(uuid4()), None]:
            if header:
                self.client.headers["X-Scenario-Owner"] = header
            else:
                self.client.headers.pop("X-Scenario-Owner", None)
            response = self.client.put("/api/v1/up-next/shows/42/episodes", json={"season_number": 1, "episode_number": 1})
            self.assertEqual(response.status_code, 403)
        self.db.scalar.assert_not_called()
        self.db.execute.assert_not_called()

    def test_episode_put_is_idempotent_and_never_creates_history(self) -> None:
        """Two identical PUTs target one unique episode, not two next episodes."""
        self.authenticate()
        with patch.object(service, "metadata", return_value={"episodes": [{"episode_number": 3, "air_date": "2020-01-01"}]}):
            for _ in range(2):
                response = self.client.put("/api/v1/up-next/shows/42/episodes", json={"season_number": 1, "episode_number": 3})
                self.assertEqual(response.status_code, 204)
        for call in self.db.execute.call_args_list:
            sql = call.args[0].compile(dialect=postgresql.dialect())
            self.assertIn("ON CONFLICT", str(sql))
            self.assertEqual(sql.params["user_id"], self.owner)
            if "episode_number" in sql.params:
                self.assertEqual(sql.params["episode_number"], 3)
            else:
                self.assertEqual(sql.params["caught_up_through"], date.min)
            self.assertNotIn("view_model", str(sql))
        self.db.add.assert_not_called()

    def test_future_missing_unknown_episode_and_tmdb_failure_do_not_write(self) -> None:
        """A client cannot claim a future episode is released."""
        self.authenticate()
        for data in [{"episodes": []}, {"episodes": [{"episode_number": 1, "air_date": None}]}, {"episodes": [{"episode_number": 1, "air_date": "2999-01-01"}]}]:
            with patch.object(service, "metadata", return_value=data):
                self.assertEqual(self.client.put("/api/v1/up-next/shows/42/episodes", json={"season_number": 1, "episode_number": 1}).status_code, 422)
        with patch.object(service, "metadata", side_effect=RuntimeError("unavailable")):
            self.assertEqual(self.client.put("/api/v1/up-next/shows/42/episodes", json={"season_number": 1, "episode_number": 1}).status_code, 503)
        self.db.execute.assert_not_called()

    def test_bulk_cutoff_never_rewinds_or_advances_on_retry(self) -> None:
        """A submitted date, not the retry date, controls catch-up."""
        self.authenticate()
        row = SimpleNamespace(caught_up_through=date(2026, 10, 1))
        self.db.scalar.return_value = row
        with patch.object(service, "metadata", return_value={}), patch.object(service, "regular_episodes", return_value=[
            service.EpisodeRef(season_number=1, episode_number=1, name="Old", air_date=date(2026, 10, 2)),
            service.EpisodeRef(season_number=1, episode_number=2, name="Later", air_date=date(2026, 10, 11)),
        ]):
            for _ in range(2):
                self.assertEqual(self.client.put("/api/v1/up-next/shows/42/caught-up", json={"through": "2026-10-10"}).status_code, 204)
        self.assertEqual(row.caught_up_through, date(2026, 10, 1))
        sql = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertEqual(sql.params["episode_number_m0"], 1)
        self.assertNotIn("episode_number_m1", sql.params)
        self.assertEqual(self.client.put("/api/v1/up-next/shows/42/caught-up", json={"through": "2999-01-01"}).status_code, 422)

    def test_season_marks_only_verified_released_episodes_through_submitted_date(self) -> None:
        """Season writes never catch up earlier seasons, unknown dates or future releases."""
        self.authenticate()
        catalog = {"episodes": [
            {"episode_number": 1, "air_date": "2020-01-01"},
            {"episode_number": 3, "air_date": "2026-10-11"},
            {"episode_number": 4, "air_date": None},
            {"episode_number": 5, "air_date": "2999-01-01"},
        ]}
        with patch.object(service, "metadata", return_value=catalog):
            for _ in range(2):
                response = self.client.put("/api/v1/up-next/shows/42/seasons/2", json={"through": "2026-10-10"})
                self.assertEqual(response.status_code, 204)
        statements = [call.args[0].compile(dialect=postgresql.dialect()) for call in self.db.execute.call_args_list]
        self.assertEqual(statements[0].params["caught_up_through"], date.min)
        self.assertEqual(statements[1].params["episode_number_m0"], 1)
        self.assertEqual(statements[1].params["season_number_m0"], 2)
        self.assertNotIn("episode_number_m1", statements[1].params)
        self.assertTrue(all("view_model" not in str(statement) for statement in statements))

    def test_new_actions_require_matching_owner_and_reject_specials_future_and_bad_metadata(self) -> None:
        """No tracking baseline is written when validation or verification fails."""
        self.authenticate()
        self.client.headers["X-Scenario-Owner"] = str(uuid4())
        self.assertEqual(self.client.put("/api/v1/up-next/shows/42/tracking").status_code, 403)
        self.assertEqual(self.client.put("/api/v1/up-next/shows/42/seasons/1", json={"through": "2020-01-01"}).status_code, 403)
        self.client.headers["X-Scenario-Owner"] = str(self.owner)
        self.assertEqual(self.client.put("/api/v1/up-next/shows/42/seasons/0", json={"through": "2020-01-01"}).status_code, 422)
        self.assertEqual(self.client.put("/api/v1/up-next/shows/42/seasons/1", json={"through": "2999-01-01"}).status_code, 422)
        with patch.object(service, "metadata", return_value={"episodes": []}):
            self.assertEqual(self.client.put("/api/v1/up-next/shows/42/seasons/1", json={"through": "2020-01-01"}).status_code, 422)
        with patch.object(service, "metadata", side_effect=RuntimeError("unavailable")):
            self.assertEqual(self.client.put("/api/v1/up-next/shows/42/tracking").status_code, 503)
        self.db.execute.assert_not_called()

    def test_start_is_idempotent_and_cannot_reset_saved_progress(self) -> None:
        """Starting a show never implies viewing or slides an existing baseline."""
        self.authenticate()
        with patch.object(service, "metadata", return_value={"id": 42}):
            for _ in range(2):
                self.assertEqual(self.client.put("/api/v1/up-next/shows/42/tracking").status_code, 204)
        for call in self.db.execute.call_args_list:
            sql = call.args[0].compile(dialect=postgresql.dialect())
            self.assertIn("ON CONFLICT DO NOTHING", str(sql))
            self.assertEqual(sql.params["caught_up_through"], date.min)
            self.assertEqual(sql.params["user_id"], self.owner)
        self.db.add.assert_not_called()

    def test_progress_read_owner_no_store_and_released_only(self) -> None:
        """Details can read partial progress with no whole-show history prerequisite."""
        self.authenticate()
        self.db.scalar.return_value = SimpleNamespace(caught_up_through=date.min)
        self.db.scalars.return_value.all.return_value = [SimpleNamespace(season_number=2, episode_number=1, watched=True)]
        episodes = [service.EpisodeRef(season_number=season, episode_number=1, name="Episode", air_date=day) for season, day in [(1, date(2020, 1, 1)), (2, date(2020, 1, 2)), (3, date(2999, 1, 1))]]
        endpoint = next(route.endpoint for route in router.routes if route.path == "/shows/{tmdb_id}/progress")
        with patch.object(service, "metadata", return_value={}), patch.object(service, "regular_episodes", return_value=episodes), patch.dict(endpoint.__globals__, {"action_states": MagicMock(return_value=[])}):
            response = self.client.get("/api/v1/up-next/shows/42/progress")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.json()["user_id"], str(self.owner))
        self.assertEqual([ep["watched"] for ep in response.json()["episodes"]], [False, True])
        self.db.execute.assert_not_called()

    def test_refresh_requires_owner_and_returns_accepted_without_history_writes(self) -> None:
        """Explicit refresh schedules public jobs; GET remains the polling endpoint."""
        self.authenticate()
        refresh = MagicMock()
        endpoint = next(route.endpoint for route in router.routes if route.path == "/refresh")
        with patch.dict(endpoint.__globals__, {"refresh_owner_catalogs": refresh}):
            self.assertEqual(self.client.post("/api/v1/up-next/refresh?language=fr-FR").status_code, 202)
            refresh.assert_called_once_with(self.db, self.owner, "fr-FR")
            self.client.headers["X-Scenario-Owner"] = str(uuid4())
            self.assertEqual(self.client.post("/api/v1/up-next/refresh").status_code, 403)
            self.assertEqual(refresh.call_count, 1)
        self.db.execute.assert_not_called()

    def test_ordered_intents_require_owner_strict_targets_and_return_private_receipts(self) -> None:
        """A cold catalogue never weakens authentication or accepts client air dates."""
        self.authenticate()
        endpoint = next(route.endpoint for route in router.routes if route.path == "/shows/{tmdb_id}/actions")
        body = dict(id=str(uuid4()), season_number=1, episode_number=2, through="2026-01-01", watched=True)
        from app.schemas.up_next import ProgressActionState
        submit = MagicMock(return_value=ProgressActionState(**body, status="pending"))
        with patch.dict(endpoint.__globals__, {"submit_action": submit}):
            response = self.client.put("/api/v1/up-next/shows/42/actions", json=body)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.headers["cache-control"], "private, no-store")
            self.assertEqual(response.json()["status"], "pending")
            self.assertEqual(submit.call_args.args[:3], (self.db, self.owner, 42))
            for invalid in [dict(body, season_number=0), dict(body, season_number=None), dict(body, watched="true"), dict(body, air_date="2020-01-01"), dict(body, user_id=str(self.owner))]:
                self.assertEqual(self.client.put("/api/v1/up-next/shows/42/actions", json=invalid).status_code, 422)
            self.client.headers["X-Scenario-Owner"] = str(uuid4())
            self.assertEqual(self.client.put("/api/v1/up-next/shows/42/actions", json=body).status_code, 403)
            self.assertEqual(submit.call_count, 1)

    def test_exclude_and_restore_are_idempotent_owner_bound_preferences_only(self) -> None:
        """No view, bookmark, cutoff or episode record is mutated by exclusions."""
        self.authenticate()
        for _ in range(2):
            self.assertEqual(self.client.put("/api/v1/up-next/shows/42/exclusion", json={"title": "A show", "poster_path": "/poster.jpg"}).status_code, 204)
        for call in self.db.execute.call_args_list:
            sql = call.args[0].compile(dialect=postgresql.dialect())
            self.assertIn("INSERT INTO show_exclusion", str(sql))
            self.assertIn("ON CONFLICT DO NOTHING", str(sql))
            self.assertEqual(sql.params["user_id"], self.owner)
        self.db.execute.reset_mock()
        for _ in range(2):
            self.assertEqual(self.client.delete("/api/v1/up-next/shows/42/exclusion").status_code, 204)
        for call in self.db.execute.call_args_list:
            sql = call.args[0].compile(dialect=postgresql.dialect())
            self.assertIn("DELETE FROM show_exclusion", str(sql))
            self.assertEqual(sql.params["user_id_1"], self.owner)
            self.assertEqual(sql.params["tmdb_id_1"], 42)
        self.db.add.assert_not_called()

    def test_exclusion_requires_owner_guard_and_validated_display_snapshot(self) -> None:
        """Private snapshots reject foreign ownership, arbitrary fields and external image URLs."""
        self.assertEqual(self.client.delete("/api/v1/up-next/shows/42/exclusion").status_code, 403)
        self.authenticate()
        for body in [{"title": "", "poster_path": ""}, {"title": "Show", "poster_path": "https://example.test/poster"}, {"title": "Show", "poster_path": "", "user_id": str(uuid4())}]:
            self.assertEqual(self.client.put("/api/v1/up-next/shows/42/exclusion", json=body).status_code, 422)
        self.client.headers["X-Scenario-Owner"] = str(uuid4())
        self.assertEqual(self.client.put("/api/v1/up-next/shows/42/exclusion", json={"title": "Show", "poster_path": ""}).status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/up-next/shows/42/exclusion").status_code, 403)
        self.db.execute.assert_not_called()


class MetadataContracts(TestCase):
    """Persist public information only and forbid accidental inline fetches."""

    def test_cache_reuses_public_metadata_by_locale_and_expires(self) -> None:
        """No account identifier is part of cached source data or its cache key."""
        db = MagicMock()
        with patch.object(service, "stored_metadata", return_value={"id": 42}) as stored:
            service.metadata("/tv/42", "en-US", db)
            service.metadata("/tv/42", "fr-FR", db)
        self.assertEqual(stored.call_args_list[0].args, (db, "/tv/42", "en-US"))
        self.assertEqual(stored.call_args_list[1].args, (db, "/tv/42", "fr-FR"))

    def test_failed_request_is_not_cached_and_storage_stays_bounded(self) -> None:
        """Retry can actually contact TMDB after failure without unbounded cache growth."""
        with patch.object(service, "stored_metadata") as stored:
            with self.assertRaises(RuntimeError):
                service.metadata("/tv/42", "en-US")
            stored.assert_not_called()

    def test_cors_allows_identity_guard_for_existing_approved_origin(self) -> None:
        """Cross-origin credentialed PUTs can carry the new identity-change guard."""
        with patch.dict(sys.modules, {"app.core.settings": stub("app.core.settings", settings=SimpleNamespace(ALLOWED_ORIGINS=["https://fixture.test"]))}):
            from app.core.middleware import setup_cors
        app = FastAPI()
        setup_cors(app)
        response = TestClient(app).options("/api/v1/up-next/shows/42/episodes", headers={
            "Origin": "https://fixture.test", "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "Content-Type,X-Scenario-Owner",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "https://fixture.test")
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")


class MigrationContracts(TestCase):
    """Compile real PostgreSQL DDL and preserve history-conversion semantics."""

    def test_upgrade_seeds_unique_current_cutoffs_not_view_dates_and_downgrade_is_scoped(self) -> None:
        """Migration works offline and never modifies any existing history row."""
        path = Path(__file__).parents[1] / "app/database/migrations/versions/202610181800_0017_episode_progress.py"
        spec = importlib.util.spec_from_file_location("progress_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = io.StringIO()
        operations = Operations(MigrationContext.configure(url="postgresql://", opts={"as_sql": True, "output_buffer": output}))
        with patch.object(module, "op", operations):
            module.upgrade()
            module.downgrade()
        sql = output.getvalue()
        self.assertIn("SELECT DISTINCT viewer_id, tmdb_id", sql)
        self.assertIn("AT TIME ZONE 'UTC'", sql)
        self.assertIn("season_number > 0", sql)
        self.assertIn("FOREIGN KEY(user_id, tmdb_id)", sql)
        self.assertNotIn("UPDATE view_model", sql)
        self.assertNotIn("DELETE FROM view_model", sql)
        self.assertNotIn("recorded_at", sql)
        self.assertNotIn("DROP TABLE view_model", sql)

    def test_new_show_view_creates_fixed_cutoff_without_rewriting_duplicates(self) -> None:
        """Old clients start tracking too; repeated whole-show additions cannot slide it."""
        owner = uuid4()
        db = MagicMock()
        payload = ViewCreate(viewer_id=owner, tmdb_id=42, media_type="tv", title="Show", poster_path="", backdrop_path="", release_date="2020-01-01", release_year="2020", runtime=100, genre_ids=[])
        add_view(payload, SimpleNamespace(id=owner), db)
        sql = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertIn("ON CONFLICT (user_id, tmdb_id) DO UPDATE", str(sql))
        self.assertEqual(sql.params["caught_up_through_1"], date.min)
        self.assertEqual(sql.params["caught_up_through"], service.utc_today())

    def test_last_show_view_removal_clears_only_that_owners_progress(self) -> None:
        """Legacy duplicate views keep progress until the final one is removed."""
        owner = uuid4()
        db = MagicMock()
        row = SimpleNamespace(id=uuid4(), viewer_id=owner, tmdb_id=42, media_type="tv")
        db.query.return_value.filter.return_value.first.return_value = row
        db.scalar.return_value = uuid4()
        delete_view(row.id, SimpleNamespace(id=owner), db)
        db.execute.assert_not_called()
        db.scalar.return_value = None
        delete_view(row.id, SimpleNamespace(id=owner), db)
        self.assertEqual(db.execute.call_count, 3)
        for call in db.execute.call_args_list:
            sql = call.args[0].compile(dialect=postgresql.dialect())
            self.assertEqual(sql.params["user_id_1"], owner)
            self.assertEqual(sql.params["tmdb_id_1"], 42)
