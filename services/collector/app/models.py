from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cybernews_runtime.audit import AuditFields


class Base(DeclarativeBase):
    """Collector Service metadata."""


class RssSource(Base):
    __tablename__ = "rss_sources"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_rss_revision"),
        CheckConstraint("content_policy IN ('external_source','full_article')", name="ck_rss_policy"),
        CheckConstraint(
            "(content_policy = 'external_source' AND NOT allow_images) OR rights_reference IS NOT NULL",
            name="ck_rss_rights",
        ),
        CheckConstraint("status IN ('pending','running','ok','not_modified','error')", name="ck_rss_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160))
    feed_url: Mapped[str] = mapped_column(Text)
    feed_key: Mapped[str] = mapped_column(String(64), unique=True)
    website_url: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    last_error: Mapped[str | None] = mapped_column(String(80))
    processed_count: Mapped[int] = mapped_column(default=0, server_default="0")
    content_policy: Mapped[str] = mapped_column(String(16), default="external_source", server_default="external_source")
    rights_reference: Mapped[str | None] = mapped_column(Text)
    allow_images: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    etag: Mapped[str | None] = mapped_column(String(512))
    last_modified: Mapped[str | None] = mapped_column(String(512))
    validator_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncRun(Base):
    __tablename__ = "rss_sync_runs"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','completed','partial','failed','interrupted')", name="ck_sync_status"),
        CheckConstraint("trigger IN ('startup','scheduled','manual')", name="ck_sync_trigger"),
        Index("uq_sync_live_run", text("(1)"), unique=True, postgresql_where=text("status IN ('queued','running')")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    trigger: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("rss_sources.id"))
    requested_by: Mapped[UUID | None]
    request_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRun(Base):
    __tablename__ = "rss_source_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running','ok','not_modified','error','interrupted')", name="ck_source_run_status"),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("rss_sync_runs.id"), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("rss_sources.id"), primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(80))
    seen: Mapped[int] = mapped_column(default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(default=0, server_default="0")
    created: Mapped[int] = mapped_column(default=0, server_default="0")
    updated: Mapped[int] = mapped_column(default=0, server_default="0")
    unchanged: Mapped[int] = mapped_column(default=0, server_default="0")
    conflicted: Mapped[int] = mapped_column(default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CollectorAudit(AuditFields, Base):
    __tablename__ = "collector_audit"
