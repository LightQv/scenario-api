"""Add default-off consent for release titles on subscribed devices.

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
"""
from alembic import op
import sqlalchemy as sa

revision: str = "u1v2w3x4y5z6"
down_revision: str = "t0u1v2w3x4y5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep every existing account on generic notifications without changing opt-in."""
    op.add_column("notification_preference", sa.Column("show_details", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Remove display consent only, retaining devices, schedules and release receipts."""
    op.drop_column("notification_preference", "show_details")
