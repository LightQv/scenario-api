"""0008_add_download_request_queue_fields

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-06-21 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "f6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "download_request_model",
        sa.Column("download_title", sa.String(), nullable=True),
    )
    op.add_column(
        "download_request_model",
        sa.Column("download_client", sa.String(), nullable=True),
    )
    op.add_column(
        "download_request_model",
        sa.Column("quality", sa.String(), nullable=True),
    )
    op.add_column(
        "download_request_model",
        sa.Column("size", sa.Integer(), nullable=True),
    )
    op.add_column(
        "download_request_model",
        sa.Column("size_left", sa.Integer(), nullable=True),
    )
    op.add_column(
        "download_request_model",
        sa.Column("time_left", sa.String(), nullable=True),
    )
    op.add_column(
        "download_request_model",
        sa.Column("tracked_download_status", sa.String(), nullable=True),
    )
    op.add_column(
        "download_request_model",
        sa.Column("tracked_download_state", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("download_request_model", "tracked_download_state")
    op.drop_column("download_request_model", "tracked_download_status")
    op.drop_column("download_request_model", "time_left")
    op.drop_column("download_request_model", "size_left")
    op.drop_column("download_request_model", "size")
    op.drop_column("download_request_model", "quality")
    op.drop_column("download_request_model", "download_client")
    op.drop_column("download_request_model", "download_title")
