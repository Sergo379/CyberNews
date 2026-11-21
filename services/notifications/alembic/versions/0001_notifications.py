"""Create subscriptions, event deduplication and user notifications."""

import sqlalchemy as sa
from alembic import op

revision = "0001_notifications"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("category", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
    )
    op.create_index("ix_subscriptions_category_date", "subscriptions", ["category", "created_at"])
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("event_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("processed_events.event_id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False, server_default="article.published"),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "event_id", name="uq_notification_user_event"),
        sa.CheckConstraint("event_type = 'article.published'", name="ck_notification_event_type"),
    )
    op.create_index("ix_notifications_user_date", "notifications", ["user_id", "created_at", "id"])
    op.create_index("ix_notifications_unread", "notifications", ["user_id"], postgresql_where=sa.text("read_at IS NULL"))


def downgrade():
    op.drop_table("notifications")
    op.drop_table("processed_events")
    op.drop_table("subscriptions")
