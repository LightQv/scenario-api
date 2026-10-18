"""Read-only private viewing insight snapshots."""

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import View
from app.schemas.insights import InsightView, ViewInsights


class InsightsService:
    """Read only the authenticated owner's current records."""

    def __init__(self, database_session: Session) -> None:
        """Store the request's database session."""
        self.database_session: Session = database_session

    def views(self, owner_id: UUID) -> ViewInsights:
        """Build a single allowlisted snapshot without interpreting legacy dates.

        Args:
            owner_id: Authenticated user ID, never a caller-supplied query filter.

        Returns:
            Current movie/show records and nullable UTC recording instants.
        """
        statement = select(View).where(
            View.viewer_id == owner_id, View.media_type.in_(["movie", "tv"])
        )
        rows: list[View] = list(self.database_session.scalars(statement).all())
        return ViewInsights(
            views=[InsightView.model_validate(row) for row in rows]
        )
