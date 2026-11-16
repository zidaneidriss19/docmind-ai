"""Add owned documents and durable storage operation states."""

import sqlalchemy as sa
from alembic import op

revision = "0002_documents"
down_revision = "0001_users_and_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.CHAR(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_documents_size"),
        sa.CheckConstraint("page_count > 0", name="ck_documents_page_count"),
        sa.CheckConstraint(
            "status IN ('UPLOADING', 'UPLOADED', 'PROCESSING', 'READY', 'FAILED', 'DELETING')",
            name="ck_documents_status",
        ),
    )
    op.create_index(
        "ix_documents_owner_created", "documents", ["owner_id", "created_at", "id"]
    )
    op.create_index(
        "ix_documents_status_updated", "documents", ["status", "updated_at"]
    )


def downgrade() -> None:
    op.drop_table("documents")
