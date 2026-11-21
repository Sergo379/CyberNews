from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Computed, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cybernews_runtime.audit import AuditFields


class Base(DeclarativeBase):
    """Article Service metadata."""


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))


class SourcePolicyRecord(Base):
    __tablename__ = "article_source_policies"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_article_source_revision"),
        CheckConstraint("content_policy IN ('external_source','full_article')", name="ck_article_source_policy"),
        CheckConstraint(
            "(content_policy = 'external_source' AND NOT allow_images) OR rights_reference IS NOT NULL",
            name="ck_article_source_rights",
        ),
    )
    source_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int]
    content_policy: Mapped[str] = mapped_column(String(16))
    rights_reference: Mapped[str | None] = mapped_column(Text)
    allow_images: Mapped[bool]


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        CheckConstraint("status IN ('published','hidden','draft')", name="ck_article_status"),
        CheckConstraint(
            "(status = 'hidden' AND previous_status IS NOT NULL AND previous_status IN ('published','draft')) OR "
            "(status <> 'hidden' AND previous_status IS NULL)", name="ck_article_previous_status",
        ),
        CheckConstraint(
            "(content_mode = 'full_article' AND content IS NOT NULL) OR "
            "(content_mode = 'external_source' AND content IS NULL)",
            name="ck_article_content_mode",
        ),
        CheckConstraint(
            "(source_id IS NULL AND original_url IS NULL AND content_mode = 'full_article') OR "
            "(source_id IS NOT NULL AND original_url IS NOT NULL)", name="ck_article_origin",
        ),
        Index("ix_articles_search", "search_document", postgresql_using="gin"),
        Index("ix_articles_public_date", "published_at", "id", postgresql_where=text("status = 'published'")),
        Index("ix_articles_public_category", "category", "published_at", postgresql_where=text("status = 'published'")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    content_mode: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("article_source_policies.source_id"), index=True)
    source_name: Mapped[str] = mapped_column(String(160))
    source_url: Mapped[str | None] = mapped_column(Text)
    original_url: Mapped[str | None] = mapped_column(Text)
    external_guid: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(ForeignKey("categories.id"))
    language: Mapped[str] = mapped_column(String(40))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(12))
    previous_status: Mapped[str | None] = mapped_column(String(12))
    image_url: Mapped[str | None] = mapped_column(Text)
    edited: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    search_document: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, title || ' ' || coalesce(summary, ''))", persisted=True),
    )


class ArticleUrlKey(Base):
    __tablename__ = "article_url_keys"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    normalized_url: Mapped[str] = mapped_column(Text)
    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id"), index=True)


class ArticleGuidKey(Base):
    __tablename__ = "article_guid_keys"
    source_id: Mapped[UUID] = mapped_column(ForeignKey("article_source_policies.source_id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    guid: Mapped[str] = mapped_column(Text)
    article_id: Mapped[UUID] = mapped_column(ForeignKey("articles.id"), index=True)


class ArticleAudit(AuditFields, Base):
    __tablename__ = "article_audit"
