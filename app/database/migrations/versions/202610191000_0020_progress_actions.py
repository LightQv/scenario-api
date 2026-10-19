"""Queue reversible progress during catalogue preparation; prioritize interactive work.

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
"""

from alembic import op
import sqlalchemy as sa

revision: str = "s9t0u1v2w3x4"
down_revision: str = "r8s9t0u1v2w3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add owner-private commands without changing saved history or episode states."""
    op.add_column("release_catalog", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "progress_action",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_model.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=True),
        sa.Column("episode_number", sa.Integer(), nullable=True),
        sa.Column("through", sa.Date(), nullable=False),
        sa.Column("watched", sa.Boolean(), nullable=False),
        sa.Column("record_history", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("sequence", name="uq_progress_action_sequence"),
        sa.CheckConstraint("tmdb_id > 0", name="ck_progress_action_show"),
        sa.CheckConstraint("season_number IS NULL OR season_number > 0", name="ck_progress_action_season"),
        sa.CheckConstraint("episode_number IS NULL OR (season_number IS NOT NULL AND episode_number > 0)", name="ck_progress_action_episode"),
        sa.CheckConstraint("status IN ('pending', 'applied', 'failed', 'cancelled')", name="ck_progress_action_status"),
    )
    op.create_index("ix_progress_action_user_id", "progress_action", ["user_id"])
    op.create_index("ix_progress_action_status", "progress_action", ["status"])


def downgrade() -> None:
    """Discard queued commands only on an explicit rollback."""
    op.drop_table("progress_action")
    op.drop_column("release_catalog", "priority")
