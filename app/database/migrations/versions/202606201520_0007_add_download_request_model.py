"""0007_add_download_request_model

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-06-20 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f6g7h8i9j0k1"
down_revision: Union[str, Sequence[str], None] = "e5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "download_request_model",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("radarr_movie_id", sa.Integer(), nullable=True),
        sa.Column(
            "genre_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("ARRAY[0]"),
            nullable=False,
        ),
        sa.Column("poster_path", sa.String(), server_default="", nullable=False),
        sa.Column("backdrop_path", sa.String(), server_default="", nullable=False),
        sa.Column("release_date", sa.String(), server_default="", nullable=False),
        sa.Column("release_year", sa.String(), server_default="", nullable=False),
        sa.Column("runtime", sa.Integer(), server_default="0", nullable=False),
        sa.Column("title", sa.String(), server_default="", nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_model.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_download_request_tmdb_type_source",
        "download_request_model",
        ["tmdb_id", "media_type", "source"],
        unique=False,
    )
    op.create_index(
        "idx_download_request_status",
        "download_request_model",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_download_request_user",
        "download_request_model",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_download_request_user", table_name="download_request_model")
    op.drop_index("idx_download_request_status", table_name="download_request_model")
    op.drop_index(
        "idx_download_request_tmdb_type_source",
        table_name="download_request_model",
    )
    op.drop_table("download_request_model")
