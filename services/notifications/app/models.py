from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Notification Service metadata."""


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_category_date", "category", "created_at"),)

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    article_id: Mapped[UUID]
    category: Mapped[str] = mapped_column(String(32))
    event_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_notification_user_event"),
        CheckConstraint("event_type = 'article.published'", name="ck_notification_event_type"),
        Index("ix_notifications_user_date", "user_id", "created_at", "id"),
        Index("ix_notifications_unread", "user_id", postgresql_where=text("read_at IS NULL")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID]
    article_id: Mapped[UUID]
    event_id: Mapped[UUID] = mapped_column(ForeignKey("processed_events.event_id"))
    event_type: Mapped[str] = mapped_column(String(40), server_default="article.published")
    category: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
