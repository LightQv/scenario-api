"""0013_scope_owned_media_by_user

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-07-01 17:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, Sequence[str], None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DELETE FROM owned_media_model")
    op.execute("DELETE FROM integration_sync_status")

    op.drop_index("uq_owned_media_movie_tmdb_type_source", table_name="owned_media_model")
    op.drop_index("uq_owned_media_episode_tmdb_type_source_season_episode", table_name="owned_media_model")
    op.drop_index("idx_owned_media_tmdb_type", table_name="owned_media_model")
    op.drop_index("idx_owned_media_tmdb_type_source", table_name="owned_media_model")
    op.drop_index("idx_owned_media_tv_episode", table_name="owned_media_model")

    op.add_column(
        "owned_media_model",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_owned_media_user_id_user_model",
        "owned_media_model",
        "user_model",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_owned_media_model_user_id"), "owned_media_model", ["user_id"])
    op.create_index(
        "uq_owned_media_movie_tmdb_type_source",
        "owned_media_model",
        ["user_id", "tmdb_id", "media_type", "source"],
        unique=True,
        postgresql_where=sa.text("scope = 'movie'"),
    )
    op.create_index(
        "uq_owned_media_episode_tmdb_type_source_season_episode",
        "owned_media_model",
        ["user_id", "tmdb_id", "media_type", "source", "season_number", "episode_number"],
        unique=True,
        postgresql_where=sa.text("scope = 'episode'"),
    )
    op.create_index("idx_owned_media_user_tmdb_type", "owned_media_model", ["user_id", "tmdb_id", "media_type"])
    op.create_index(
        "idx_owned_media_user_tmdb_type_source",
        "owned_media_model",
        ["user_id", "tmdb_id", "media_type", "source"],
    )
    op.create_index(
        "idx_owned_media_user_tv_episode",
        "owned_media_model",
        ["user_id", "tmdb_id", "season_number", "episode_number"],
    )

    op.drop_constraint(
        "uq_integration_sync_status_source_media_type",
        "integration_sync_status",
        type_="unique",
    )
    op.drop_index("idx_integration_sync_status_source_media_type", table_name="integration_sync_status")
    op.add_column(
        "integration_sync_status",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_integration_sync_status_user_id_user_model",
        "integration_sync_status",
        "user_model",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_integration_sync_status_user_id"), "integration_sync_status", ["user_id"])
    op.create_unique_constraint(
        "uq_integration_sync_status_user_source_media_type",
        "integration_sync_status",
        ["user_id", "source", "media_type"],
    )
    op.create_index(
        "idx_integration_sync_status_user_source_media_type",
        "integration_sync_status",
        ["user_id", "source", "media_type"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM owned_media_model")
    op.execute("DELETE FROM integration_sync_status")

    op.drop_index("idx_integration_sync_status_user_source_media_type", table_name="integration_sync_status")
    op.drop_constraint(
        "uq_integration_sync_status_user_source_media_type",
        "integration_sync_status",
        type_="unique",
    )
    op.drop_index(op.f("ix_integration_sync_status_user_id"), table_name="integration_sync_status")
    op.drop_constraint("fk_integration_sync_status_user_id_user_model", "integration_sync_status", type_="foreignkey")
    op.drop_column("integration_sync_status", "user_id")
    op.create_index("idx_integration_sync_status_source_media_type", "integration_sync_status", ["source", "media_type"])
    op.create_unique_constraint(
        "uq_integration_sync_status_source_media_type",
        "integration_sync_status",
        ["source", "media_type"],
    )

    op.drop_index("idx_owned_media_user_tv_episode", table_name="owned_media_model")
    op.drop_index("idx_owned_media_user_tmdb_type_source", table_name="owned_media_model")
    op.drop_index("idx_owned_media_user_tmdb_type", table_name="owned_media_model")
    op.drop_index("uq_owned_media_episode_tmdb_type_source_season_episode", table_name="owned_media_model")
    op.drop_index("uq_owned_media_movie_tmdb_type_source", table_name="owned_media_model")
    op.drop_index(op.f("ix_owned_media_model_user_id"), table_name="owned_media_model")
    op.drop_constraint("fk_owned_media_user_id_user_model", "owned_media_model", type_="foreignkey")
    op.drop_column("owned_media_model", "user_id")
    op.create_index(
        "uq_owned_media_movie_tmdb_type_source",
        "owned_media_model",
        ["tmdb_id", "media_type", "source"],
        unique=True,
        postgresql_where=sa.text("scope = 'movie'"),
    )
    op.create_index(
        "uq_owned_media_episode_tmdb_type_source_season_episode",
        "owned_media_model",
        ["tmdb_id", "media_type", "source", "season_number", "episode_number"],
        unique=True,
        postgresql_where=sa.text("scope = 'episode'"),
    )
    op.create_index("idx_owned_media_tmdb_type", "owned_media_model", ["tmdb_id", "media_type"])
    op.create_index("idx_owned_media_tmdb_type_source", "owned_media_model", ["tmdb_id", "media_type", "source"])
    op.create_index("idx_owned_media_tv_episode", "owned_media_model", ["tmdb_id", "season_number", "episode_number"])
