"""Create the article catalog and seed categories."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0001_articles"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    categories = op.create_table(
        "categories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
    )
    op.bulk_insert(categories, [
        {"id": "vulnerabilities", "name": "Vulnerabilities"}, {"id": "malware", "name": "Malware"},
        {"id": "data-breaches", "name": "Data Breaches"}, {"id": "cyberattacks", "name": "Cyberattacks"},
        {"id": "research", "name": "Research"}, {"id": "software-security", "name": "Software Security"},
        {"id": "other", "name": "Other"},
    ])
    op.create_table(
        "article_source_policies",
        sa.Column("source_id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_policy", sa.String(16), nullable=False),
        sa.Column("rights_reference", sa.Text()),
        sa.Column("allow_images", sa.Boolean(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_article_source_revision"),
        sa.CheckConstraint("content_policy IN ('external_source','full_article')", name="ck_article_source_policy"),
        sa.CheckConstraint(
            "(content_policy = 'external_source' AND NOT allow_images) OR rights_reference IS NOT NULL",
            name="ck_article_source_rights",
        ),
    )
    op.create_table(
        "articles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("content", sa.Text()),
        sa.Column("content_mode", sa.String(16), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("article_source_policies.source_id")),
        sa.Column("source_name", sa.String(160), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("original_url", sa.Text()),
        sa.Column("external_guid", sa.Text()),
        sa.Column("author", sa.String(160)),
        sa.Column("category", sa.String(32), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("previous_status", sa.String(12)),
        sa.Column("image_url", sa.Text()),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("search_document", TSVECTOR(),
                  sa.Computed("to_tsvector('simple'::regconfig, title || ' ' || coalesce(summary, ''))", persisted=True),
                  nullable=False),
        sa.CheckConstraint("status IN ('published','hidden','draft')", name="ck_article_status"),
        sa.CheckConstraint(
            "(status = 'hidden' AND previous_status IS NOT NULL AND previous_status IN ('published','draft')) OR "
            "(status <> 'hidden' AND previous_status IS NULL)", name="ck_article_previous_status",
        ),
        sa.CheckConstraint(
            "(content_mode = 'full_article' AND content IS NOT NULL) OR "
            "(content_mode = 'external_source' AND content IS NULL)", name="ck_article_content_mode",
        ),
        sa.CheckConstraint(
            "(source_id IS NULL AND original_url IS NULL AND content_mode = 'full_article') OR "
            "(source_id IS NOT NULL AND original_url IS NOT NULL)", name="ck_article_origin",
        ),
    )
    op.create_index("ix_articles_search", "articles", ["search_document"], postgresql_using="gin")
    op.create_index("ix_articles_public_date", "articles", ["published_at", "id"],
                    postgresql_where=sa.text("status = 'published'"))
    op.create_index("ix_articles_public_category", "articles", ["category", "published_at"],
                    postgresql_where=sa.text("status = 'published'"))
    op.create_index("ix_articles_source_id", "articles", ["source_id"])
    op.create_table(
        "article_url_keys",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("articles.id"), nullable=False),
    )
    op.create_index("ix_article_url_keys_article_id", "article_url_keys", ["article_id"])
    op.create_table(
        "article_guid_keys",
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("article_source_policies.source_id"), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("guid", sa.Text(), nullable=False),
        sa.Column("article_id", sa.Uuid(), sa.ForeignKey("articles.id"), nullable=False),
    )
    op.create_index("ix_article_guid_keys_article_id", "article_guid_keys", ["article_id"])
    op.create_table(
        "article_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reason", sa.Text()),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
    )
    op.create_index("ix_article_audit_actor_id", "article_audit", ["actor_id"])


def downgrade():
    op.drop_table("article_audit")
    op.drop_table("article_guid_keys")
    op.drop_table("article_url_keys")
    op.drop_table("articles")
    op.drop_table("article_source_policies")
    op.drop_table("categories")
