"""Hermetic contracts: no settings files, network services or persistent database.

Run: .venv/bin/python -m unittest discover -s contract_tests -v
The historical pytest conftest imports the removed app.core.database module.
These tests intentionally avoid that unrelated bootstrap and application startup.
"""

import importlib.util
import sys
import io
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy import Column
from alembic.migration import MigrationContext
from alembic.operations import Operations


def stub(name: str, **attributes: object) -> ModuleType:
    """Create an external-boundary module without reading application settings."""
    module: ModuleType = ModuleType(name)
    module.__dict__.update(attributes)
    return module


sys.modules.update({
    "app.core.logger": stub("app.core.logger", log=MagicMock()),
    "app.database.session": stub("app.database.session", get_database_session=MagicMock()),
    "app.core.security": stub("app.core.security", verify_token=lambda token: None),
    "app.services.api_token_service": stub("app.services.api_token_service", resolve_bearer_api_token=MagicMock()),
})
from app.api.dependencies import get_current_user, get_database
from app.api.v1.insights import router
from app.api.v1.views import router as legacy_router, add_view
from app.models import View
from app.schemas.insights import InsightView
from app.schemas.view import ViewCreate, ViewResponse


class InsightsContracts(TestCase):
    """Exercise actual route dependencies, response schemas and query predicates."""

    def setUp(self) -> None:
        """Build an isolated API with in-memory session doubles."""
        self.owner = uuid4()
        self.other = uuid4()
        self.row = SimpleNamespace(
            id=uuid4(), viewer_id=self.owner, tmdb_id=42, title="Fixture",
            media_type="movie", runtime=123, genre_ids=[0, 18], poster_path="",
            backdrop_path="", release_date="1999-01-01", release_year="1999",
            recorded_at=None, created_at=datetime(2020, 1, 1), secret="not exposed",
        )
        self.database = MagicMock()
        self.database.scalars.return_value.all.return_value = [self.row]
        self.database.query.return_value.filter.return_value.all.return_value = [self.row]
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/v1/insights")
        self.app.include_router(legacy_router, prefix="/api/v1/views")
        self.app.dependency_overrides[get_database] = lambda: self.database
        self.client = TestClient(self.app)

    def authenticate(self) -> None:
        """Use a trusted authenticated-owner fixture, not a caller ID."""
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=self.owner)

    def test_anonymous_denied_before_private_query(self) -> None:
        """Missing cookie cannot query private history."""
        response = self.client.get("/api/v1/insights/views")
        self.assertEqual(response.status_code, 403)
        self.database.scalars.assert_not_called()

    def test_owner_bound_allowlisted_no_store_snapshot(self) -> None:
        """A forged user query cannot alter the SQL owner predicate."""
        self.authenticate()
        response = self.client.get(f"/api/v1/insights/views?user_id={self.other}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        body = response.json()
        self.assertEqual(body["date_semantics"], "recorded_at")
        self.assertIsNone(body["views"][0]["recorded_at"])
        self.assertNotIn("created_at", body["views"][0])
        self.assertNotIn("secret", body["views"][0])
        statement = self.database.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertEqual(statement.params["viewer_id_1"], self.owner)
        self.assertEqual(statement.params["media_type_1"], ["movie", "tv"])
        self.database.commit.assert_not_called()

    def test_dates_keep_unknowns_and_normalize_only_explicit_offsets(self) -> None:
        """Legacy created_at is never a fallback; naive recording dates are unknown."""
        for date in [None, datetime(2026, 1, 1)]:
            self.row.recorded_at = date
            self.assertIsNone(InsightView.model_validate(self.row).recorded_at)
        self.row.recorded_at = datetime.fromisoformat("2026-01-01T23:00:00-08:00")
        self.assertEqual(InsightView.model_validate(self.row).recorded_at, datetime(2026, 1, 2, 7, tzinfo=timezone.utc))

    def test_legacy_response_shape_and_post_success_are_unchanged(self) -> None:
        """Old clients see the same public fields and watched success body."""
        self.row.recorded_at = datetime.now(timezone.utc)
        response = self.client.get(f"/api/v1/views/{self.owner}")
        self.assertEqual(set(response.json()[0]), set(ViewResponse.model_fields))
        payload = ViewCreate.model_validate(vars(self.row))
        result = add_view(payload, SimpleNamespace(id=self.owner), self.database)
        self.assertEqual(result, {"message": "View added successfully"})
        stored = self.database.add.call_args.args[0]
        self.assertIsNotNone(stored.recorded_at.utcoffset())
        self.assertNotIn("recorded_at", ViewCreate.model_fields)

    def test_migration_is_nullable_without_default_or_backfill_and_reversible(self) -> None:
        """DDL adds only an unknown-by-default timezone-aware field."""
        path = Path(__file__).parents[1] / "app/database/migrations/versions/202610181300_0016_add_view_recorded_at.py"
        spec = importlib.util.spec_from_file_location("recording_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module, "op") as operations:
            module.upgrade()
            table, column = operations.add_column.call_args.args
            self.assertEqual(table, "view_model")
            self.assertTrue(column.nullable)
            self.assertTrue(column.type.timezone)
            self.assertIsNone(column.server_default)
            self.assertIsNone(column.default)
            operations.execute.assert_not_called()
            module.downgrade()
            operations.drop_column.assert_called_once_with("view_model", "recorded_at")
        self.assertIsNone(View.__table__.c.recorded_at.default)

    def test_postgres_migration_sql_never_fills_historical_rows(self) -> None:
        """Compile actual PostgreSQL DDL offline without opening a database."""
        buffer = io.StringIO()
        context = MigrationContext.configure(url="postgresql://", opts={"as_sql": True, "output_buffer": buffer})
        operations = Operations(context)
        column = View.__table__.c.recorded_at
        operations.add_column("view_model", Column(column.name, column.type, nullable=column.nullable))
        sql = buffer.getvalue()
        self.assertIn("TIMESTAMP WITH TIME ZONE", sql)
        self.assertNotIn("DEFAULT", sql)
        self.assertNotIn("NOT NULL", sql)
        self.assertNotIn("UPDATE", sql)
