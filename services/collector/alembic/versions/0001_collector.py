"""Create RSS sources and persistent run history."""

from hashlib import sha256
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "0001_collector"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    sources = op.create_table(
        "rss_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=False),
        sa.Column("feed_key", sa.String(64), unique=True, nullable=False),
        sa.Column("website_url", sa.Text(), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.String(80)),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_policy", sa.String(16), nullable=False, server_default="external_source"),
        sa.Column("rights_reference", sa.Text()),
        sa.Column("allow_images", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("etag", sa.String(512)),
        sa.Column("last_modified", sa.String(512)),
        sa.Column("validator_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("revision >= 1", name="ck_rss_revision"),
        sa.CheckConstraint("content_policy IN ('external_source','full_article')", name="ck_rss_policy"),
        sa.CheckConstraint(
            "(content_policy = 'external_source' AND NOT allow_images) OR rights_reference IS NOT NULL",
            name="ck_rss_rights",
        ),
        sa.CheckConstraint("status IN ('pending','running','ok','not_modified','error')", name="ck_rss_status"),
    )
    seeds = [
        ("6646d4df-be28-4155-a2fc-2c6c2caae34e", "The Hacker News",
         "https://feeds.feedburner.com/TheHackersNews", "https://thehackernews.com/"),
        ("af9be391-7fbf-4694-b89f-29da74e7fa3d", "BleepingComputer",
         "https://www.bleepingcomputer.com/feed/", "https://www.bleepingcomputer.com/"),
        ("b1b32f91-e42d-4942-928b-5be83fc9752f", "Krebs on Security",
         "https://krebsonsecurity.com/feed/", "https://krebsonsecurity.com/"),
    ]
    op.bulk_insert(sources, [
        {"id": UUID(identifier), "name": name, "feed_url": feed,
         "feed_key": sha256(feed.encode()).hexdigest(), "website_url": website, "language": "en"}
        for identifier, name, feed, website in seeds
    ])
    op.create_table(
        "rss_sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("trigger", sa.String(12), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("rss_sources.id")),
        sa.Column("requested_by", sa.Uuid()),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('queued','running','completed','partial','failed','interrupted')", name="ck_sync_status"),
        sa.CheckConstraint("trigger IN ('startup','scheduled','manual')", name="ck_sync_trigger"),
    )
    op.create_index("ix_rss_sync_runs_created_at", "rss_sync_runs", ["created_at"])
    op.create_index("uq_sync_live_run", "rss_sync_runs", [sa.text("(1)")],
                    unique=True, postgresql_where=sa.text("status IN ('queued','running')"))
    op.create_table(
        "rss_source_runs",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("rss_sync_runs.id"), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("rss_sources.id"), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(80)),
        *(sa.Column(field, sa.Integer(), nullable=False, server_default="0")
          for field in ("seen", "skipped", "created", "updated", "unchanged", "conflicted")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('running','ok','not_modified','error','interrupted')", name="ck_source_run_status"),
    )
    op.create_index("ix_rss_source_runs_source_id", "rss_source_runs", ["source_id"])
    op.create_table(
        "collector_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reason", sa.Text()),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
    )
    op.create_index("ix_collector_audit_actor_id", "collector_audit", ["actor_id"])


def downgrade():
    op.drop_table("collector_audit")
    op.drop_table("rss_source_runs")
    op.drop_table("rss_sync_runs")
    op.drop_table("rss_sources")
