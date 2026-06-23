"""0011_add_sonarr_tv_scope_fields

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-06-22 21:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, Sequence[str], None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("owned_media_model", schema=None) as batch_op:
        batch_op.add_column(sa.Column("scope", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("tvdb_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sonarr_series_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("season_number", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("episode_number", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("episode_title", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("episode_air_date", sa.String(), nullable=True))

    op.execute("UPDATE owned_media_model SET scope = 'movie' WHERE scope IS NULL")

    with op.batch_alter_table("owned_media_model", schema=None) as batch_op:
        batch_op.alter_column("scope", existing_type=sa.String(length=50), nullable=False)
        batch_op.drop_constraint("uq_owned_media_tmdb_type_source", type_="unique")
        batch_op.create_index(
            "idx_owned_media_tmdb_type_source",
            ["tmdb_id", "media_type", "source"],
            unique=False,
        )
        batch_op.create_index(
            "idx_owned_media_tv_episode",
            ["tmdb_id", "season_number", "episode_number"],
            unique=False,
        )

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

    with op.batch_alter_table("download_request_model", schema=None) as batch_op:
        batch_op.add_column(sa.Column("scope", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("tvdb_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sonarr_series_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sonarr_search_command_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sonarr_episode_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("season_number", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("episode_number", sa.Integer(), nullable=True))

    op.execute("UPDATE download_request_model SET scope = 'movie' WHERE scope IS NULL")

    with op.batch_alter_table("download_request_model", schema=None) as batch_op:
        batch_op.alter_column("scope", existing_type=sa.String(length=50), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("download_request_model", schema=None) as batch_op:
        batch_op.drop_column("episode_number")
        batch_op.drop_column("season_number")
        batch_op.drop_column("sonarr_episode_id")
        batch_op.drop_column("sonarr_search_command_id")
        batch_op.drop_column("sonarr_series_id")
        batch_op.drop_column("tvdb_id")
        batch_op.drop_column("scope")

    op.drop_index(
        "uq_owned_media_episode_tmdb_type_source_season_episode",
        table_name="owned_media_model",
        postgresql_where=sa.text("scope = 'episode'"),
    )
    op.drop_index(
        "uq_owned_media_movie_tmdb_type_source",
        table_name="owned_media_model",
        postgresql_where=sa.text("scope = 'movie'"),
    )

    with op.batch_alter_table("owned_media_model", schema=None) as batch_op:
        batch_op.drop_index("idx_owned_media_tv_episode")
        batch_op.drop_index("idx_owned_media_tmdb_type_source")
        batch_op.create_unique_constraint(
            "uq_owned_media_tmdb_type_source",
            ["tmdb_id", "media_type", "source"],
        )
        batch_op.drop_column("episode_air_date")
        batch_op.drop_column("episode_title")
        batch_op.drop_column("episode_number")
        batch_op.drop_column("season_number")
        batch_op.drop_column("sonarr_series_id")
        batch_op.drop_column("tvdb_id")
        batch_op.drop_column("scope")
