import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.ingestion_content import (
    IngestionError,
    TextChunk,
    embed_texts,
    extract_pdf,
    load_pdf,
    validate_vectors,
)
from app.ingestion_queue import Publisher, PublishError
from app.models import Document, DocumentChunk, ProcessingJob
from app.storage import ObjectStorage, StorageError, get_storage

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=20)
REPUBLISH_AFTER = timedelta(minutes=2)
DISPATCH_BACKOFF = timedelta(seconds=10)
Embedder = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True, slots=True)
class Work:
    job_id: UUID
    document_id: UUID
    attempt: int
    storage_key: str
    checksum: str


def lock_job_and_document(db: Session, job_id: UUID):
    document_id = db.scalar(
        select(ProcessingJob.document_id).where(ProcessingJob.id == job_id)
    )
    if document_id is None:
        return None, None
    # Upload, deletion and retry also take the document lock before touching jobs.
    document = db.get(Document, document_id, with_for_update=True)
    if document is None or document.status == "DELETING":
        return None, None
    return db.get(ProcessingJob, job_id, with_for_update=True), document


def claim(engine: Engine, job_id: UUID) -> Work | None:
    with Session(engine) as db, db.begin():
        job, document = lock_job_and_document(db, job_id)
        now = datetime.now(UTC)
        if (
            job is None
            or document is None
            or job.status != "PENDING"
            or job.available_at > now
            or document.status != "UPLOADED"
        ):
            return None
        job.attempts += 1
        job.status = "RUNNING"
        job.lease_until = now + LEASE
        document.status = "PROCESSING"
        document.processing_error = None
        return Work(
            job.id,
            document.id,
            job.attempts,
            document.storage_key,
            document.checksum_sha256,
        )


def still_running(
    job: ProcessingJob | None, document: Document | None, attempt: int
) -> bool:
    return (
        job is not None
        and document is not None
        and job.status == "RUNNING"
        and job.attempts == attempt
        and document.status == "PROCESSING"
    )


def complete(
    engine: Engine,
    work: Work,
    page_count: int,
    chunks: list[TextChunk],
    vectors: list[list[float]],
) -> bool:
    with Session(engine) as db, db.begin():
        job, document = lock_job_and_document(db, work.job_id)
        if not still_running(job, document, work.attempt):
            return False
        db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == work.document_id)
        )
        db.add_all(
            DocumentChunk(
                document_id=work.document_id,
                chunk_index=index,
                page_number=chunk.page_number,
                content=chunk.content,
                embedding=vector,
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        )
        job.status = "SUCCEEDED"
        job.lease_until = None
        job.error_code = None
        document.page_count = page_count
        document.status = "READY"
        return True


def apply_failure(
    job: ProcessingJob, document: Document, code: str, *, retry: bool
) -> None:
    job.lease_until = None
    job.error_code = code
    if retry and job.attempts < MAX_ATTEMPTS:
        next_run = datetime.now(UTC) + timedelta(seconds=5 * 4 ** (job.attempts - 1))
        job.status = "PENDING"
        job.available_at = next_run
        job.publish_after = next_run
        document.status = "UPLOADED"
    else:
        job.status = "FAILED"
        document.status = "FAILED"
        document.processing_error = code


def fail(engine: Engine, work: Work, code: str, *, retry: bool) -> None:
    with Session(engine) as db, db.begin():
        job, document = lock_job_and_document(db, work.job_id)
        if still_running(job, document, work.attempt):
            apply_failure(job, document, code, retry=retry)


def run_job(
    engine: Engine,
    job_id: UUID,
    *,
    storage: ObjectStorage | None = None,
    embed: Embedder = embed_texts,
) -> bool:
    work = claim(engine, job_id)
    if work is None:
        return False

    try:
        pdf = load_pdf(
            storage if storage is not None else get_storage(),
            work.storage_key,
            work.checksum,
        )
        page_count, chunks = extract_pdf(pdf)
        vectors = embed([chunk.content for chunk in chunks])
        validate_vectors(vectors, len(chunks))
    except IngestionError as exc:
        fail(engine, work, exc.code, retry=False)
        return False
    except (StorageError, OSError, ValueError, RuntimeError, ImportError) as exc:
        logger.warning(
            "Ingestion %s attempt %d: %s", job_id, work.attempt, type(exc).__name__
        )
        fail(engine, work, "INGESTION_UNAVAILABLE", retry=True)
        return False

    return complete(engine, work, page_count, chunks, vectors)


def recover_expired(engine: Engine, *, limit: int = 32) -> int:
    now = datetime.now(UTC)
    with Session(engine) as db:
        expired = db.scalars(
            select(ProcessingJob.id)
            .where(ProcessingJob.status == "RUNNING", ProcessingJob.lease_until <= now)
            .order_by(ProcessingJob.lease_until)
            .limit(limit)
        ).all()

    recovered = 0
    for job_id in expired:
        with Session(engine) as db, db.begin():
            job, document = lock_job_and_document(db, job_id)
            if (
                job is not None
                and document is not None
                and job.status == "RUNNING"
                and job.lease_until <= now
            ):
                apply_failure(job, document, "WORKER_INTERRUPTED", retry=True)
                recovered += 1
    return recovered


def publish_pending(engine: Engine, send: Publisher, *, limit: int = 32) -> int:
    sent = 0
    for _ in range(limit):
        with Session(engine) as db, db.begin():
            now = datetime.now(UTC)
            job = db.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.status == "PENDING",
                    ProcessingJob.available_at <= now,
                    ProcessingJob.publish_after <= now,
                )
                .order_by(ProcessingJob.available_at, ProcessingJob.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                break
            try:
                send(job.id)
            except (PublishError, OSError) as exc:
                logger.warning(
                    "Could not publish ingestion job: %s", type(exc).__name__
                )
                job.publish_after = now + DISPATCH_BACKOFF
                break
            job.publish_after = now + REPUBLISH_AFTER
            sent += 1
    return sent
