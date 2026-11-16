from datetime import UTC, datetime, timedelta
from typing import Annotated, BinaryIO, Literal
from unicodedata import category
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from python_multipart.exceptions import MultipartParseError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException

from app.auth import CurrentUser, Database, require_same_origin_request
from app.errors import APIError
from app.models import Document
from app.pdf import CHUNK_BYTES, MAX_MULTIPART_BYTES, pdf_metadata, too_large
from app.storage import StorageError, get_storage

PUBLIC_STATES = ("UPLOADED", "PROCESSING", "READY", "FAILED")
MUTATION = [Depends(require_same_origin_request)]
TOO_LARGE = "Document request exceeds the size limit."


def prevent_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/documents", tags=["documents"], dependencies=[Depends(prevent_caching)]
)

DocumentStatus = Literal["UPLOADED", "PROCESSING", "READY", "FAILED"]


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    size_bytes: int
    page_count: int | None
    status: DocumentStatus
    created_at: datetime


class DocumentState(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: DocumentStatus
    page_count: int | None
    updated_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentResponse]
    next_offset: int | None


class DeletionAccepted(BaseModel):
    id: UUID
    status: Literal["DELETING"] = "DELETING"


def owned_document(
    db: Session, owner_id: UUID, document_id: UUID, *, lock: bool = False
) -> Document:
    query = select(Document).where(
        Document.id == document_id,
        Document.owner_id == owner_id,
        Document.status.in_(PUBLIC_STATES),
    )
    document = db.scalar(query.with_for_update() if lock else query)
    if document is None:
        raise APIError(404, "DOCUMENT_NOT_FOUND", "The document was not found.")
    return document


def upload_name(value: str | None) -> str:
    name = (value or "").replace(chr(92), "/").rsplit("/", 1)[-1].strip()
    name = "".join(char for char in name if not category(char).startswith("C"))
    if not name.lower().endswith(".pdf") or len(name) <= 4 or len(name) > 255:
        raise APIError(
            400,
            "INVALID_FILENAME",
            "A PDF filename of up to 255 characters is required.",
        )
    return name


def persist_pdf(db: Session, owner_id: UUID, file: UploadFile) -> DocumentResponse:
    filename = upload_name(file.filename)
    size, checksum = pdf_metadata(file.file)
    storage = get_storage()
    document_id = uuid4()
    key = f"{owner_id}/{document_id}.pdf"
    db.add(
        Document(
            id=document_id,
            owner_id=owner_id,
            filename=filename,
            storage_key=key,
            mime_type="application/pdf",
            size_bytes=size,
            checksum_sha256=checksum,
            status="UPLOADING",
        )
    )
    db.commit()
    # Keep the intent durable and lock it while writing. Storage failures leave
    # a hidden intent that the recovery command can reconcile safely.
    with db.begin():
        document = db.get(Document, document_id, with_for_update=True)
        if document is None:
            raise APIError(503, "UPLOAD_EXPIRED", "The upload expired. Try again.")
        storage.put(key, file.file, size)
        document.status = "UPLOADED"
        db.flush()
        return DocumentResponse.model_validate(document)


@router.post(
    "",
    status_code=202,
    dependencies=MUTATION,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload(request: Request, db: Database, user: CurrentUser) -> DocumentResponse:
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "multipart/form-data"
    ):
        raise APIError(
            415, "MULTIPART_REQUIRED", "Send one PDF as multipart form data."
        )
    length = request.headers.get("content-length")
    if length is not None and length.isdecimal() and int(length) > MAX_MULTIPART_BYTES:
        raise too_large()

    received = 0

    async def receive_limited():
        nonlocal received
        message = await request.receive()
        received += len(message.get("body", b""))
        if received > MAX_MULTIPART_BYTES:
            raise MultiPartException(TOO_LARGE)
        return message

    limited = Request(request.scope, receive_limited)
    try:
        async with limited.form(max_files=1, max_fields=0) as form:
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise APIError(
                    400, "PDF_REQUIRED", "The multipart file field is required."
                )
            return await run_in_threadpool(persist_pdf, db, user.id, file)
    except MultipartParseError as exc:
        raise APIError(
            400, "INVALID_MULTIPART", "The multipart body is malformed."
        ) from exc
    except HTTPException as exc:
        if exc.detail == TOO_LARGE:
            raise too_large() from exc
        raise APIError(
            400, "INVALID_MULTIPART", "Send exactly one PDF in the file field."
        ) from exc


@router.get("")
def list_documents(
    db: Database,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
) -> DocumentList:
    documents = db.scalars(
        select(Document)
        .where(Document.owner_id == user.id, Document.status.in_(PUBLIC_STATES))
        .order_by(Document.created_at.desc(), Document.id.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return DocumentList(
        items=[
            DocumentResponse.model_validate(document) for document in documents[:limit]
        ],
        next_offset=offset + limit if len(documents) > limit else None,
    )


@router.get("/{document_id}")
def get_document(
    document_id: UUID, db: Database, user: CurrentUser
) -> DocumentResponse:
    return DocumentResponse.model_validate(owned_document(db, user.id, document_id))


@router.get("/{document_id}/status")
def get_status(document_id: UUID, db: Database, user: CurrentUser) -> DocumentState:
    return DocumentState.model_validate(owned_document(db, user.id, document_id))


def read_chunks(stream: BinaryIO):
    try:
        while chunk := stream.read(CHUNK_BYTES):
            yield chunk
    finally:
        stream.close()


@router.get("/{document_id}/file", response_class=StreamingResponse)
def download(document_id: UUID, db: Database, user: CurrentUser) -> StreamingResponse:
    document = owned_document(db, user.id, document_id)
    key, filename, size = document.storage_key, document.filename, document.size_bytes
    db.rollback()
    stream = get_storage().open(key)
    return StreamingResponse(
        read_chunks(stream),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "Content-Length": str(size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
        background=BackgroundTask(stream.close),
    )


def purge_document(db: Session, document: Document) -> None:
    get_storage().delete(document.storage_key)
    db.delete(document)


@router.delete("/{document_id}", status_code=202, dependencies=MUTATION)
def delete_document(
    document_id: UUID, db: Database, user: CurrentUser
) -> DeletionAccepted:
    document = owned_document(db, user.id, document_id, lock=True)
    document.status = "DELETING"
    db.commit()
    try:
        with db.begin():
            deleting = db.get(Document, document_id, with_for_update=True)
            if deleting is not None:
                purge_document(db, deleting)
    except StorageError:
        # Persisted DELETING state allows an operator to retry safely.
        pass
    return DeletionAccepted(id=document_id)


@router.post("/{document_id}/retry", status_code=202, dependencies=MUTATION)
def retry_document(document_id: UUID, db: Database, user: CurrentUser) -> DocumentState:
    document = owned_document(db, user.id, document_id, lock=True)
    if document.status != "FAILED":
        raise APIError(
            409, "DOCUMENT_NOT_FAILED", "Only failed documents can be queued again."
        )
    document.status = "UPLOADED"
    document.page_count = None
    db.flush()
    result = DocumentState.model_validate(document)
    db.commit()
    return result


def recover_storage(db: Session, limit: int = 100) -> tuple[int, int]:
    stale = datetime.now(UTC) - timedelta(hours=1)
    eligible = or_(
        Document.status == "DELETING",
        and_(Document.status == "UPLOADING", Document.updated_at <= stale),
    )
    recovered = failed = 0
    attempted: list[UUID] = []
    while len(attempted) < limit:
        try:
            with db.begin():
                document = db.scalar(
                    select(Document)
                    .where(eligible, Document.id.notin_(attempted))
                    .order_by(Document.updated_at, Document.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if document is None:
                    break
                attempted.append(document.id)
                purge_document(db, document)
        except StorageError:
            failed += 1
        else:
            recovered += 1
    return recovered, failed
