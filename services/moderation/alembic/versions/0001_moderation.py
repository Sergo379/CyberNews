"""Create CyberNews moderation tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001_moderation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "comment_restrictions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("lifted_at", sa.DateTime(timezone=True)),
        sa.Column("lifted_by", sa.Uuid()),
        sa.CheckConstraint(
            "(active AND lifted_at IS NULL AND lifted_by IS NULL) OR "
            "(NOT active AND lifted_at IS NOT NULL AND lifted_by IS NOT NULL)",
            name="ck_restriction_lift",
        ),
    )
    op.create_index("ix_comment_restrictions_user_id", "comment_restrictions", ["user_id"])
    op.create_index("uq_active_comment_restriction", "comment_restrictions", ["user_id"],
                    unique=True, postgresql_where=sa.text("active"))
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.Uuid()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("target_type IN ('comment', 'article', 'user')", name="ck_report_target_type"),
        sa.CheckConstraint(
            "(status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR "
            "(status IN ('reviewed', 'rejected') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_report_review",
        ),
    )
    op.create_index("ix_reports_queue", "reports", ["status", "created_at"])
    op.create_table(
        "moderation_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reason", sa.Text()),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
    )
    op.create_index("ix_moderation_audit_actor_id", "moderation_audit", ["actor_id"])


def downgrade():
    op.drop_table("moderation_audit")
    op.drop_table("reports")
    op.drop_table("comment_restrictions")
