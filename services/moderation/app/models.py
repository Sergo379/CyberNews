from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cybernews_runtime.audit import AuditFields


class Base(DeclarativeBase):
    """Moderation Service metadata."""


class Restriction(Base):
    __tablename__ = "comment_restrictions"
    __table_args__ = (
        CheckConstraint(
            "(active AND lifted_at IS NULL AND lifted_by IS NULL) OR "
            "(NOT active AND lifted_at IS NOT NULL AND lifted_by IS NOT NULL)",
            name="ck_restriction_lift",
        ),
        Index("uq_active_comment_restriction", "user_id", unique=True, postgresql_where=text("active")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(index=True)
    created_by: Mapped[UUID]
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lifted_by: Mapped[UUID | None]


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint("target_type IN ('comment', 'article', 'user')", name="ck_report_target_type"),
        CheckConstraint(
            "(status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR "
            "(status IN ('reviewed', 'rejected') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_report_review",
        ),
        Index("ix_reports_queue", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    author_id: Mapped[UUID]
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[UUID]
    reason: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    reviewed_by: Mapped[UUID | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModerationAudit(AuditFields, Base):
    __tablename__ = "moderation_audit"
