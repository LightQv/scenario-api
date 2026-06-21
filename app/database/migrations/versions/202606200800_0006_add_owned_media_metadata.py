"""0006_add_owned_media_metadata

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-06-20 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("owned_media_model", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "genre_ids",
                postgresql.ARRAY(sa.Integer()),
                server_default=sa.text("ARRAY[0]"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("poster_path", sa.String(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("backdrop_path", sa.String(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("release_date", sa.String(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("release_year", sa.String(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("runtime", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("title", sa.String(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("metadata_synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("owned_media_model", schema=None) as batch_op:
        batch_op.drop_column("metadata_synced_at")
        batch_op.drop_column("title")
        batch_op.drop_column("runtime")
        batch_op.drop_column("release_year")
        batch_op.drop_column("release_date")
        batch_op.drop_column("backdrop_path")
        batch_op.drop_column("poster_path")
        batch_op.drop_column("genre_ids")
