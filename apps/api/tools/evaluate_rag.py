"""Evaluate local retrieval, citation and abstention on a synthetic PDF corpus."""

import json
from hashlib import sha256
from io import BytesIO
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pymupdf
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.chat_models import Conversation, ConversationDocument
from app.ingestion import run_job
from app.models import Document, ProcessingJob, User
from app.rag import NO_ANSWER, generate_answer, query_vector, retrieve
from app.storage import LocalStorage


def make_pdf(pages: list[str]) -> bytes:
    with pymupdf.open() as pdf:
        for text in pages:
            pdf.new_page().insert_text((66, 72), text)
        return pdf.tobytes()


def canonical(text: str) -> str:
    return "".join(char for char in text.casefold() if char.isalnum())


def evaluate(engine, storage, owner, dataset):
    docs = {}
    for name, pages in dataset["documents"].items():
        body = make_pdf(pages)
        doc_id, job_id = uuid4(), uuid4()
        key = f"{owner}/{doc_id}.pdf"
        storage.put(key, BytesIO(body), len(body))
        with Session(engine) as db, db.begin():
            db.add(
                Document(
                    id=doc_id,
                    owner_id=owner,
                    filename=name,
                    storage_key=key,
                    mime_type="application/pdf",
                    size_bytes=len(body),
                    checksum_sha256=sha256(body).hexdigest(),
                    status="UPLOADED",
                )
            )
            db.flush()
            db.add(ProcessingJob(id=job_id, document_id=doc_id))
        if not run_job(engine, job_id, storage=storage):
            raise RuntimeError(f"Unable to index fixture {name}")
        docs[name] = doc_id

    conversation_id = uuid4()
    with Session(engine) as db, db.begin():
        db.add(Conversation(id=conversation_id, owner_id=owner, title="RAG evaluation"))
        db.flush()
        db.add_all(
            ConversationDocument(conversation_id=conversation_id, document_id=id_)
            for id_ in docs.values()
        )

    results = []
    for case in dataset["cases"]:
        question = case["question"]
        vector = query_vector(question)
        with Session(engine) as db:
            sources = retrieve(db, conversation_id, owner, vector)
        answer = generate_answer(question, sources)
        if "document" not in case:
            results.append(
                {
                    "id": case["id"],
                    "retrieved_sources": len(sources),
                    "abstained": answer.content == NO_ANSWER and not answer.sources,
                }
            )
            continue
        expected = (docs[case["document"]], case["page"])
        results.append(
            {
                "id": case["id"],
                "retrieval_hit": any(
                    (source.document_id, source.page) == expected for source in sources
                ),
                "citation_hit": any(
                    (source.document_id, source.page) == expected
                    for source in answer.sources
                ),
                "answer_hit": canonical(case["answer_contains"])
                in canonical(answer.content),
            }
        )
    return results


def main() -> int:
    url = environ.get("DOCMIND_TEST_DATABASE_URL")
    if not url or not url.endswith("/docmind_test"):
        raise RuntimeError("The benchmark requires the isolated docmind_test database.")
    dataset = json.loads(
        Path(__file__).with_name("rag_cases.json").read_text(encoding="utf-8")
    )
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    owner = uuid4()
    try:
        with Session(engine) as db, db.begin():
            db.add(
                User(
                    id=owner,
                    email=f"benchmark-{owner}@example.com",
                    password_hash="benchmark-only",
                )
            )
        with TemporaryDirectory() as directory:
            results = evaluate(engine, LocalStorage(Path(directory)), owner, dataset)
        print(json.dumps(results, indent=2))
        return int(
            any(
                not all(
                    result[key]
                    for key in result
                    if key.endswith("_hit") or key == "abstained"
                )
                for result in results
            )
        )
    finally:
        with Session(engine) as db, db.begin():
            db.execute(delete(Conversation).where(Conversation.owner_id == owner))
            db.execute(delete(Document).where(Document.owner_id == owner))
            db.execute(delete(User).where(User.id == owner))
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
