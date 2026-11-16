"""Store shared request counters with bounded windows."""

import sqlalchemy as sa
from alembic import op

revision = "0005_request_limits"
down_revision = "0004_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_limits",
        sa.Column("scope", sa.String(30), primary_key=True),
        sa.Column("subject", sa.String(64), primary_key=True),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("hits > 0", name="ck_request_limits_hits"),
    )
    op.create_index("ix_request_limits_expires_at", "request_limits", ["expires_at"])


def downgrade() -> None:
    op.drop_table("request_limits")
