from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Community Service metadata."""


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint("length(body) BETWEEN 1 AND 5000", name="ck_comments_body_length"),
        CheckConstraint(
            "(status = 'published' AND removed_at IS NULL) OR "
            "(status IN ('hidden', 'deleted') AND removed_at IS NOT NULL)",
            name="ck_comments_lifecycle",
        ),
        Index("ix_comments_public_order", "article_id", "created_at", "id",
              postgresql_where=text("status = 'published'")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    article_id: Mapped[UUID] = mapped_column(index=True)
    author_id: Mapped[UUID]
    nickname: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="published", server_default="published")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moderated_by: Mapped[UUID | None]
    moderation_reason: Mapped[str | None] = mapped_column(Text)


class ArticleReaction(Base):
    __tablename__ = "article_reactions"
    __table_args__ = (CheckConstraint("reaction IN ('like','dislike')", name="ck_article_reaction"),)

    target_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    reaction: Mapped[str] = mapped_column(String(8))


class CommentReaction(Base):
    __tablename__ = "comment_reactions"
    __table_args__ = (CheckConstraint("reaction IN ('like','dislike')", name="ck_comment_reaction"),)

    target_id: Mapped[UUID] = mapped_column(ForeignKey("comments.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    reaction: Mapped[str] = mapped_column(String(8))


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (Index("ix_bookmarks_user_date", "user_id", "created_at", "article_id"),)

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    article_id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MutationBucket(Base):
    __tablename__ = "community_rate_buckets"

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(16), primary_key=True)
    count: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class CommentModeration(Base):
    __tablename__ = "comment_moderation_history"
    __table_args__ = (
        CheckConstraint("action IN ('hide', 'restore')", name="ck_comment_moderation_action"),
        CheckConstraint("result IN ('applied', 'no_change')", name="ck_comment_moderation_result"),
        Index("ix_comment_moderation_date", "comment_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    comment_id: Mapped[UUID] = mapped_column(ForeignKey("comments.id"))
    actor_id: Mapped[UUID]
    actor_role: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(12))
    request_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
