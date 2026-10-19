"""Persist public release catalogues and reversible episode overrides.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "r8s9t0u1v2w3"
down_revision: str = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve every existing episode as watched; create an empty public cache."""
    op.add_column("episode_progress", sa.Column("watched", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "release_catalog",
        sa.Column("media_type", sa.String(5), primary_key=True),
        sa.Column("tmdb_id", sa.Integer(), primary_key=True),
        sa.Column("language", sa.String(5), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("tmdb_id > 0", name="ck_release_catalog_tmdb"),
        sa.CheckConstraint("media_type IN ('movie', 'tv')", name="ck_release_catalog_type"),
        sa.CheckConstraint("language IN ('en-US', 'fr-FR')", name="ck_release_catalog_language"),
    )
    op.create_index("ix_release_catalog_next_refresh_at", "release_catalog", ["next_refresh_at"])


def downgrade() -> None:
    """Remove catalogue data and explicit unwatched overrides only on deliberate rollback."""
    op.drop_table("release_catalog")
    # False overrides must not turn into watched rows after removing the flag.
    op.execute("DELETE FROM episode_progress WHERE watched = false")
    op.drop_column("episode_progress", "watched")
