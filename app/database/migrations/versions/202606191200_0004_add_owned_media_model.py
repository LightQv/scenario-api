"""0004_add_owned_media_model

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-06-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6g7h8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "owned_media_model",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tmdb_id",
            "media_type",
            "source",
            name="uq_owned_media_tmdb_type_source",
        ),
    )
    with op.batch_alter_table("owned_media_model", schema=None) as batch_op:
        batch_op.create_index(
            "idx_owned_media_tmdb_type",
            ["tmdb_id", "media_type"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("owned_media_model", schema=None) as batch_op:
        batch_op.drop_index("idx_owned_media_tmdb_type")

    op.drop_table("owned_media_model")
