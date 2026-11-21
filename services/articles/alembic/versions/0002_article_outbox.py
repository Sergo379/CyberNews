"""Persist first-publication events without backfilling the existing catalog."""

import sqlalchemy as sa
from alembic import op

revision = "0002_article_outbox"
down_revision = "0001_articles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("articles", sa.Column("ever_published", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(
        "UPDATE articles SET ever_published = true "
        "WHERE status = 'published' OR (status = 'hidden' AND previous_status = 'published')"
    )
    op.create_table(
        "article_outbox",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("articles.id"), unique=True, nullable=False),
        sa.Column("category", sa.String(32), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("source_id", sa.Uuid()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_article_outbox_pending", "article_outbox", ["next_attempt_at", "event_id"],
                    postgresql_where=sa.text("delivered_at IS NULL"))


def downgrade():
    op.drop_table("article_outbox")
    op.drop_column("articles", "ever_published")
