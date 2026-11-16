from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, Database, require_same_origin_request
from app.chat_models import Citation, Conversation, ConversationDocument, Message
from app.documents import prevent_caching
from app.errors import APIError
from app.models import Document, DocumentChunk
from app.rag import Answer, generate_answer, query_vector, retrieve, revalidate_sources

MUTATION = [Depends(require_same_origin_request)]
router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
    dependencies=[Depends(prevent_caching)],
)
PageSize = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=2_147_483_647)]


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[UUID] = Field(min_length=1, max_length=10)


class NewConversation(Selection):
    title: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=150, pattern=r"^[^\x00]+$"
        ),
    ]


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=4000, pattern=r"^[^\x00]+$"
        ),
    ]


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    document_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class ConversationPage(BaseModel):
    items: list[ConversationResponse]
    next_offset: int | None


class CitationResponse(BaseModel):
    id: UUID
    document_id: UUID
    page_number: int
    chunk_id: UUID
    excerpt: str


class MessageResponse(BaseModel):
    message_id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationResponse]
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageResponse]
    next_offset: int | None


def owned_conversation(
    db: Session, owner_id: UUID, conversation_id: UUID, *, lock: bool = False
) -> Conversation:
    query = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.owner_id == owner_id
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise APIError(404, "CONVERSATION_NOT_FOUND", "The conversation was not found.")
    return row


def validate_selection(db: Session, owner_id: UUID, ids: list[UUID]) -> None:
    if len(set(ids)) != len(ids):
        raise APIError(422, "DUPLICATE_DOCUMENT", "Choose each document once.")
    documents = db.scalars(
        select(Document)
        .where(Document.owner_id == owner_id, Document.id.in_(ids))
        .order_by(Document.id)
        .with_for_update(read=True)
    ).all()
    if len(documents) != len(ids):
        raise APIError(404, "DOCUMENT_NOT_FOUND", "A selected document was not found.")
    if any(document.status != "READY" for document in documents):
        raise APIError(
            409,
            "DOCUMENT_NOT_READY",
            "Wait for the selected documents to finish indexing.",
        )


def conversation_responses(
    db: Session, rows: list[Conversation]
) -> list[ConversationResponse]:
    if not rows:
        return []
    ids = {row.id: [] for row in rows}
    selected = db.execute(
        select(ConversationDocument.conversation_id, ConversationDocument.document_id)
        .join(Document, Document.id == ConversationDocument.document_id)
        .join(Conversation, Conversation.id == ConversationDocument.conversation_id)
        .where(
            ConversationDocument.conversation_id.in_(ids),
            Document.owner_id == Conversation.owner_id,
            Document.status != "DELETING",
        )
        .order_by(ConversationDocument.document_id)
    )
    for conversation_id, document_id in selected:
        ids[conversation_id].append(document_id)
    return [
        ConversationResponse(
            id=row.id,
            title=row.title,
            document_ids=ids[row.id],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.post("", status_code=201, dependencies=MUTATION)
def create_conversation(
    payload: NewConversation, db: Database, user: CurrentUser
) -> ConversationResponse:
    validate_selection(db, user.id, payload.document_ids)
    row = Conversation(owner_id=user.id, title=payload.title)
    db.add(row)
    db.flush()
    db.add_all(
        ConversationDocument(conversation_id=row.id, document_id=id_)
        for id_ in payload.document_ids
    )
    result = conversation_responses(db, [row])[0]
    db.commit()
    return result


@router.get("")
def list_conversations(
    db: Database, user: CurrentUser, limit: PageSize = 20, offset: Offset = 0
) -> ConversationPage:
    rows = list(
        db.scalars(
            select(Conversation)
            .where(Conversation.owner_id == user.id)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return ConversationPage(
        items=conversation_responses(db, rows[:limit]),
        next_offset=offset + limit if len(rows) > limit else None,
    )


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: UUID, db: Database, user: CurrentUser
) -> ConversationResponse:
    row = owned_conversation(db, user.id, conversation_id)
    return conversation_responses(db, [row])[0]


@router.put("/{conversation_id}/documents", dependencies=MUTATION)
def replace_documents(
    conversation_id: UUID, payload: Selection, db: Database, user: CurrentUser
) -> ConversationResponse:
    row = owned_conversation(db, user.id, conversation_id, lock=True)
    validate_selection(db, user.id, payload.document_ids)
    db.execute(
        delete(ConversationDocument).where(
            ConversationDocument.conversation_id == row.id
        )
    )
    db.add_all(
        ConversationDocument(conversation_id=row.id, document_id=id_)
        for id_ in payload.document_ids
    )
    row.updated_at = func.now()
    result = conversation_responses(db, [row])[0]
    db.commit()
    return result


@router.delete("/{conversation_id}", status_code=204, dependencies=MUTATION)
def delete_conversation(
    conversation_id: UUID, db: Database, user: CurrentUser
) -> Response:
    db.delete(owned_conversation(db, user.id, conversation_id, lock=True))
    db.commit()
    return Response(status_code=204)


def message_responses(
    db: Session, owner_id: UUID, rows: list[Message]
) -> list[MessageResponse]:
    if not rows:
        return []
    citations = {row.id: [] for row in rows}
    query = (
        select(Citation, DocumentChunk)
        .join(DocumentChunk, DocumentChunk.id == Citation.chunk_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Citation.message_id.in_(citations),
            Document.owner_id == owner_id,
            Document.status == "READY",
        )
        .order_by(Citation.position)
    )
    for citation, chunk in db.execute(query):
        citations[citation.message_id].append(
            CitationResponse(
                id=citation.id,
                document_id=chunk.document_id,
                page_number=citation.page_number,
                chunk_id=chunk.id,
                excerpt=chunk.content[:500],
            )
        )
    return [
        MessageResponse(
            message_id=row.id,
            role=row.role,
            content=row.content,
            citations=citations[row.id],
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/{conversation_id}/messages")
def history(
    conversation_id: UUID,
    db: Database,
    user: CurrentUser,
    limit: PageSize = 20,
    offset: Offset = 0,
) -> MessagePage:
    owned_conversation(db, user.id, conversation_id)
    rows = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return MessagePage(
        items=message_responses(db, user.id, rows[:limit]),
        next_offset=offset + limit if len(rows) > limit else None,
    )


def save_answer(
    db: Session, conversation_id: UUID, owner_id: UUID, answer: Answer
) -> MessageResponse:
    message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=answer.content,
        model_name=answer.model_name,
        prompt_tokens=answer.prompt_tokens,
        completion_tokens=answer.completion_tokens,
    )
    db.add(message)
    db.flush()
    db.add_all(
        Citation(
            message_id=message.id,
            chunk_id=source.chunk_id,
            page_number=source.page,
            position=index,
        )
        for index, source in enumerate(answer.sources, 1)
    )
    return message_responses(db, owner_id, [message])[0]


@router.post("/{conversation_id}/messages", status_code=201, dependencies=MUTATION)
def ask(
    conversation_id: UUID, payload: Question, db: Database, user: CurrentUser
) -> MessageResponse:
    owned_conversation(db, user.id, conversation_id, lock=True)
    ready = db.scalar(
        select(Document.id)
        .join(ConversationDocument, ConversationDocument.document_id == Document.id)
        .where(
            ConversationDocument.conversation_id == conversation_id,
            Document.owner_id == user.id,
            Document.status == "READY",
        )
        .limit(1)
    )
    if ready is None:
        raise APIError(
            409, "NO_READY_DOCUMENTS", "Select at least one indexed document."
        )
    db.add(
        Message(conversation_id=conversation_id, role="user", content=payload.content)
    )
    db.commit()

    vector = query_vector(payload.content)
    sources = retrieve(db, conversation_id, user.id, vector)
    db.rollback()  # Do not hold a database transaction during generation.
    answer = generate_answer(payload.content, sources)

    row = owned_conversation(db, user.id, conversation_id, lock=True)
    revalidate_sources(db, conversation_id, user.id, tuple(sources))
    row.updated_at = func.now()
    result = save_answer(db, row.id, user.id, answer)
    db.commit()
    return result
