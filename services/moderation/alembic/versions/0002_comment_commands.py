"""Keep inter-service comment commands until their result can be audited."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_comment_commands"
down_revision = "0001_moderation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "comment_moderation_commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("comment_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_role", sa.String(16), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("error_status", sa.Integer()),
        sa.Column("result", JSONB()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("action IN ('hide','restore')", name="ck_comment_commands_action"),
        sa.CheckConstraint("state IN ('pending','completed','rejected')", name="ck_comment_commands_state"),
    )
    op.create_index("ix_comment_commands_pending", "comment_moderation_commands", ["next_attempt_at", "id"],
                    postgresql_where=sa.text("state = 'pending'"))


def downgrade():
    op.drop_table("comment_moderation_commands")
