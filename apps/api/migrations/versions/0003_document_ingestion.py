"""Add durable ingestion jobs and page-linked document embeddings."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision = "0003_document_ingestion"
down_revision = "0002_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "documents", sa.Column("processing_error", sa.String(60), nullable=True)
    )
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "publish_after",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
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
        sa.CheckConstraint("attempts >= 0", name="ck_processing_jobs_attempts"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_processing_jobs_status",
        ),
    )
    op.create_index(
        "ix_processing_jobs_document_created",
        "processing_jobs",
        ["document_id", "created_at"],
    )
    op.create_index(
        "ix_processing_jobs_pending",
        "processing_jobs",
        ["status", "available_at", "publish_after"],
    )
    op.create_index(
        "ix_processing_jobs_lease", "processing_jobs", ["status", "lease_until"]
    )
    op.create_index(
        "uq_processing_jobs_active",
        "processing_jobs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", VECTOR(384), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_position"
        ),
        sa.CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index"),
        sa.CheckConstraint("page_number > 0", name="ck_document_chunks_page"),
    )
    op.execute(
        "INSERT INTO processing_jobs (id, document_id) "
        "SELECT gen_random_uuid(), id FROM documents WHERE status = 'UPLOADED'"
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("processing_jobs")
    op.drop_column("documents", "processing_error")
    # The extension can be owned by the infrastructure or shared with other schemas.
