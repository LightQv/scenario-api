"""Add opt-in release notifications without changing existing private data.

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
"""
from alembic import op
import sqlalchemy as sa

revision: str = "t0u1v2w3x4y5"
down_revision: str = "s9t0u1v2w3x4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create empty preferences/devices/outbox; users must explicitly opt in."""
    def timestamps() -> list[sa.Column]:
        """Match inherited model timestamps without touching existing tables."""
        return [sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False)]
    op.create_table("notification_preference",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_model.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("delivery_time", sa.String(5), nullable=False),
        sa.Column("language", sa.String(5), nullable=False), *timestamps())
    op.create_table("push_subscription",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user_model.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted_subscription", sa.Text(), nullable=False),
        sa.Column("last_test_at", sa.DateTime(timezone=True)), *timestamps())
    op.create_index("ix_push_subscription_user_id", "push_subscription", ["user_id"])
    op.create_table("notification_delivery",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subscription_id", sa.Uuid(), sa.ForeignKey("push_subscription.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subscription_id", "local_date", name="uq_notification_device_day"),
        sa.CheckConstraint("status IN ('pending','sent','failed','cancelled')", name="ck_notification_delivery_status"), *timestamps())
    op.create_index("ix_notification_delivery_ready", "notification_delivery", ["status", "next_attempt_at"])


def downgrade() -> None:
    """Remove notification-only data; never alter history, catalogues or progress."""
    op.drop_table("notification_delivery")
    op.drop_table("push_subscription")
    op.drop_table("notification_preference")
