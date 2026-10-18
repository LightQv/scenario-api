"""Add explicit recording dates without backfilling ambiguous legacy timestamps."""

from alembic import op
import sqlalchemy as sa

revision: str = "o5p6q7r8s9t0"
down_revision: str = "n4o5p6q7r8s9"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Add a nullable, offset-aware timestamp with no default or backfill."""
    op.add_column(
        "view_model",
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove recording dates; existing history fields remain unchanged."""
    op.drop_column("view_model", "recorded_at")
