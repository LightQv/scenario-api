"""Hermetic conversion/SQL safeguards; no production connection or settings."""

from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import MagicMock
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.database.backfill_view_dates import backfill, recording_date


class BackfillContracts(TestCase):
    """Validate explicit timezone interpretation and protected write behavior."""

    def database(self, dates: list[datetime]) -> MagicMock:
        """Build an isolated connection returning legacy candidate fixtures."""
        connection = MagicMock()
        connection.execute.return_value.mappings.return_value.all.return_value = [
            {"id": uuid4(), "created_at": date} for date in dates
        ]
        return connection

    def test_utc_and_seasonal_offsets(self) -> None:
        """Known zones convert independently of the process/server timezone."""
        self.assertEqual(recording_date(datetime(2020, 1, 1), ZoneInfo("UTC")), datetime(2020, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(recording_date(datetime(2020, 1, 1), ZoneInfo("Europe/Paris")), datetime(2019, 12, 31, 23, tzinfo=timezone.utc))
        self.assertEqual(recording_date(datetime(2020, 7, 1), ZoneInfo("Europe/Paris")), datetime(2020, 6, 30, 22, tzinfo=timezone.utc))

    def test_refuses_dst_gaps_folds_and_aware_inputs(self) -> None:
        """Neither repeated nor nonexistent local times get silently guessed."""
        for date in [datetime(2020, 3, 29, 2, 30), datetime(2020, 10, 25, 2, 30), datetime.now(timezone.utc)]:
            with self.subTest(date=date), self.assertRaises(ValueError):
                recording_date(date, ZoneInfo("Europe/Paris"))

    def test_preview_has_no_writes_and_bounded_examples(self) -> None:
        """Default operation only reads missing dates; samples exclude identities."""
        connection = self.database([datetime(2020, 1, 1)] * 8)
        report = backfill(connection, ZoneInfo("UTC"))
        self.assertEqual(report["candidates"], 8)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(len(report["examples"]), 5)
        self.assertNotIn("id", report["examples"][0])
        connection.execute.assert_called_once()
        self.assertIn("recorded_at IS NULL", str(connection.execute.call_args.args[0]))

    def test_apply_only_updates_missing_dates_preserving_creation_and_update_time(self) -> None:
        """Apply binds converted instants, locks rows and never changes Base fields."""
        connection = self.database([datetime(2020, 1, 1)])
        owner = uuid4()
        report = backfill(connection, ZoneInfo("Europe/Paris"), apply=True, expected_count=1, owner=owner)
        select, update = connection.execute.call_args_list
        self.assertIn("FOR UPDATE", str(select.args[0]))
        self.assertIn("viewer_id = :owner", str(select.args[0]))
        self.assertEqual(select.args[1], {"owner": owner})
        self.assertEqual(str(update.args[0]), "UPDATE view_model SET recorded_at = :recorded_at WHERE id = :id AND recorded_at IS NULL")
        self.assertEqual(update.args[1][0]["recorded_at"], datetime(2019, 12, 31, 23, tzinfo=timezone.utc))
        self.assertEqual(report["updated"], 1)

    def test_unsafe_dates_or_count_drift_abort_before_any_write(self) -> None:
        """All validation precedes writes, even if some candidates are valid."""
        for dates, count in [([datetime(2020, 1, 1)], 2), ([datetime(2020, 1, 1), datetime(2020, 10, 25, 2, 30)], 2)]:
            connection = self.database(dates)
            with self.assertRaises(ValueError):
                backfill(connection, ZoneInfo("Europe/Paris"), apply=True, expected_count=count)
            connection.execute.assert_called_once()

    def test_rerun_with_no_missing_dates_is_noop(self) -> None:
        """Previously populated dates cannot be overwritten on repeat execution."""
        connection = self.database([])
        self.assertEqual(backfill(connection, ZoneInfo("UTC"), apply=True, expected_count=0)["updated"], 0)
        connection.execute.assert_called_once()

    def test_apply_requires_reviewed_count(self) -> None:
        """Unreviewed apply fails before accessing the database."""
        connection = self.database([])
        with self.assertRaises(ValueError):
            backfill(connection, ZoneInfo("UTC"), apply=True)
        connection.execute.assert_not_called()
