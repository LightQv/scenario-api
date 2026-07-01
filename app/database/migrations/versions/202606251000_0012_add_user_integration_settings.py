"""0012_add_user_integration_settings

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-06-25 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, Sequence[str], None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_integration_settings_model",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("encrypted_secrets", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_model.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source", name="uq_user_integration_settings_user_source"),
    )
    op.create_index(
        "idx_user_integration_settings_user",
        "user_integration_settings_model",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_integration_settings_model_user_id"),
        "user_integration_settings_model",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_user_integration_settings_model_user_id"),
        table_name="user_integration_settings_model",
    )
    op.drop_index(
        "idx_user_integration_settings_user",
        table_name="user_integration_settings_model",
    )
    op.drop_table("user_integration_settings_model")
