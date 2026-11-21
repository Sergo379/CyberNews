"""Create local discussion, reaction, bookmark and moderation tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001_community"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("nickname", sa.String(32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="published"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("moderated_by", sa.Uuid()),
        sa.Column("moderation_reason", sa.Text()),
        sa.CheckConstraint("length(body) BETWEEN 1 AND 5000", name="ck_comments_body_length"),
        sa.CheckConstraint(
            "(status = 'published' AND removed_at IS NULL) OR "
            "(status IN ('hidden', 'deleted') AND removed_at IS NOT NULL)", name="ck_comments_lifecycle",
        ),
    )
    op.create_index("ix_comments_article_id", "comments", ["article_id"])
    op.create_index("ix_comments_public_order", "comments", ["article_id", "created_at", "id"],
                    postgresql_where=sa.text("status = 'published'"))
    op.create_table(
        "article_reactions",
        sa.Column("target_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("reaction", sa.String(8), nullable=False),
        sa.CheckConstraint("reaction IN ('like','dislike')", name="ck_article_reaction"),
    )
    op.create_table(
        "comment_reactions",
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("comments.id"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("reaction", sa.String(8), nullable=False),
        sa.CheckConstraint("reaction IN ('like','dislike')", name="ck_comment_reaction"),
    )
    op.create_table(
        "bookmarks",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("article_id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_bookmarks_user_date", "bookmarks", ["user_id", "created_at", "article_id"])
    op.create_table(
        "community_rate_buckets",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("operation", sa.String(16), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_community_rate_buckets_expires_at", "community_rate_buckets", ["expires_at"])
    op.create_table(
        "comment_moderation_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("comment_id", sa.Uuid(), sa.ForeignKey("comments.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_role", sa.String(16), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("result", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("action IN ('hide', 'restore')", name="ck_comment_moderation_action"),
        sa.CheckConstraint("result IN ('applied', 'no_change')", name="ck_comment_moderation_result"),
    )
    op.create_index("ix_comment_moderation_date", "comment_moderation_history", ["comment_id", "created_at"])


def downgrade():
    op.drop_table("comment_moderation_history")
    op.drop_table("community_rate_buckets")
    op.drop_table("bookmarks")
    op.drop_table("comment_reactions")
    op.drop_table("article_reactions")
    op.drop_table("comments")
