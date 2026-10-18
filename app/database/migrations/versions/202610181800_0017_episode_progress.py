"""Seed fixed episode-progress cutoffs without changing existing viewing history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "p6q7r8s9t0u1"
down_revision: str = "o5p6q7r8s9t0"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create private progress and assume existing viewed shows are caught up today."""
    timestamps: list[sa.Column] = [
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(),
        ),
    ]
    op.create_table(
        "show_progress",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_model.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("tmdb_id", sa.Integer(), primary_key=True),
        sa.Column("caught_up_through", sa.Date(), nullable=False),
        *timestamps,
        sa.CheckConstraint("tmdb_id > 0", name="ck_show_progress_tmdb"),
    )
    op.create_table(
        "episode_progress",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_model.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("tmdb_id", sa.Integer(), primary_key=True),
        sa.Column("season_number", sa.Integer(), primary_key=True),
        sa.Column("episode_number", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint("tmdb_id > 0", name="ck_episode_progress_tmdb"),
        sa.CheckConstraint("season_number > 0", name="ck_episode_progress_season"),
        sa.CheckConstraint("episode_number > 0", name="ck_episode_progress_episode"),
        sa.ForeignKeyConstraint(
            ["user_id", "tmdb_id"],
            ["show_progress.user_id", "show_progress.tmdb_id"],
            ondelete="CASCADE",
        ),
    )
    op.execute("""
        INSERT INTO show_progress (user_id, tmdb_id, caught_up_through)
        SELECT DISTINCT viewer_id, tmdb_id, (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date
        FROM view_model WHERE media_type = 'tv' AND tmdb_id > 0
    """)


def downgrade() -> None:
    """Remove progress only; original history is never rewritten."""
    op.drop_table("episode_progress")
    op.drop_table("show_progress")
