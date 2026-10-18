"""Add independent account-owned show exclusions without changing history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "q7r8s9t0u1v2"
down_revision: str = "p6q7r8s9t0u1"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create exclusions; no existing view, bookmark or progress is rewritten."""
    op.create_table(
        "show_exclusion",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_model.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("tmdb_id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("poster_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("tmdb_id > 0", name="ck_show_exclusion_tmdb"),
    )


def downgrade() -> None:
    """Remove exclusion preferences only."""
    op.drop_table("show_exclusion")
