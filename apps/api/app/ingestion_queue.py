from typing import Protocol
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import ProcessingJob

ACTIVE_JOBS = ("PENDING", "RUNNING")
TASK_NAME = "docmind.ingest_document"


class PublishError(Exception):
    pass


class Publisher(Protocol):
    def __call__(self, job_id: UUID) -> None: ...


def enqueue_document(db: Session, document_id: UUID) -> None:
    db.add(ProcessingJob(document_id=document_id))


def cancel_document_jobs(db: Session, document_id: UUID) -> None:
    db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.document_id == document_id,
            ProcessingJob.status.in_(ACTIVE_JOBS),
        )
        .values(status="CANCELLED", lease_until=None)
    )
