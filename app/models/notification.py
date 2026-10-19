"""Private opt-in preferences, encrypted devices and daily delivery receipts."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class NotificationPreference(Base):
    """Account-wide schedule; installing a browser never opts the user in."""

    __tablename__ = "notification_preference"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_model.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Paris")
    delivery_time: Mapped[str] = mapped_column(String(5), nullable=False, default="09:00")
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="en-US")


class PushSubscription(Base):
    """One globally unique browser endpoint, never silently reassigned to an owner."""

    __tablename__ = "push_subscription"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_model.id", ondelete="CASCADE"), index=True)
    endpoint_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    encrypted_subscription: Mapped[str] = mapped_column(Text, nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationDelivery(Base):
    """Durable per-device/day outbox; no media titles or private feed snapshots."""

    __tablename__ = "notification_delivery"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    subscription_id: Mapped[UUID] = mapped_column(ForeignKey("push_subscription.id", ondelete="CASCADE"), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index("ix_notification_delivery_ready", "status", "next_attempt_at"),
        UniqueConstraint("subscription_id", "local_date", name="uq_notification_device_day"),
        CheckConstraint("status IN ('pending','sent','failed','cancelled')", name="ck_notification_delivery_status"),
    )
