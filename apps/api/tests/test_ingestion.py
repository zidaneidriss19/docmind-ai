import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import UUID, uuid4

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import database_engine
from app.ingestion import claim, complete, publish_pending, recover_expired, run_job
from app.ingestion_content import TextChunk, chunk_page
from app.main import app
from app.models import Document, DocumentChunk, ProcessingJob, User
from app.storage import LocalStorage

MUTATION = {"X-DocMind-Request": "1"}
BASE = "/api/v1/documents"


def vectors(texts):
    return [[1.0, *([0.0] * 383)] for _ in texts]


class ChunkTest(TestCase):
    def test_long_text_never_mixes_pages_or_exceeds_chunk_size(self):
        chunks = chunk_page("Un texte lisible. " * 130, 3)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(
            all(
                chunk.page_number == 3 and 0 < len(chunk.content) <= 800
                for chunk in chunks
            )
        )
        self.assertIn(chunks[0].content[-30:], chunks[1].content)
        self.assertEqual(chunk_page(" \n\x00", 1), [])


@skipUnless(os.environ.get("DOCMIND_TEST_DATABASE_URL"), "requires migrated PostgreSQL")
class IngestionTest(TestCase):
    def setUp(self):
        os.environ["DOCMIND_DATABASE_URL"] = os.environ["DOCMIND_TEST_DATABASE_URL"]
        root = self.enterContext(TemporaryDirectory())
        self.storage = LocalStorage(Path(root))
        self.enterContext(patch("app.documents.get_storage", return_value=self.storage))
        self.client = self.enterContext(TestClient(app, base_url="https://testserver"))
        credentials = {
            "email": f"{uuid4().hex}@example.com",
            "password": "a local ingestion test password",
        }
        response = self.client.post(
            "/api/v1/auth/register", json=credentials, headers=MUTATION
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.owner = UUID(response.json()["id"])
        self.engine = database_engine()
        self.addCleanup(self.remove_records)
        response = self.client.post(
            "/api/v1/auth/login", json=credentials, headers=MUTATION
        )
        self.assertEqual(response.status_code, 200, response.text)

    def remove_records(self):
        with Session(self.engine) as db, db.begin():
            db.execute(delete(Document).where(Document.owner_id == self.owner))
            db.execute(delete(User).where(User.id == self.owner))

    def upload(self, *texts):
        with pymupdf.open() as pdf:
            for text in texts:
                page = pdf.new_page()
                if text:
                    page.insert_text((72, 72), text)
            data = pdf.tobytes()
        response = self.client.post(
            BASE,
            files={"file": ("ingestion.pdf", data, "application/pdf")},
            headers=MUTATION,
        )
        self.assertEqual(response.status_code, 202, response.text)
        doc_id = UUID(response.json()["id"])
        with Session(self.engine) as db:
            job = db.scalars(
                select(ProcessingJob).where(ProcessingJob.document_id == doc_id)
            ).one()
            self.assertEqual(job.status, "PENDING")
            return doc_id, job.id

    def document(self, doc_id):
        return self.client.get(f"{BASE}/{doc_id}/status").json()

    def test_durable_dispatch_and_duplicate_delivery(self):
        doc, job = self.upload(
            "First page about databases.", "Second page about citations."
        )
        published = []

        def unavailable(_job):
            raise ConnectionError()

        self.assertEqual(publish_pending(self.engine, unavailable), 0)
        with Session(self.engine) as db, db.begin():
            row = db.get_one(ProcessingJob, job)
            self.assertEqual(row.status, "PENDING")
            self.assertGreater(row.publish_after, datetime.now(UTC))
            row.publish_after = datetime.now(UTC) - timedelta(seconds=1)
        self.assertEqual(publish_pending(self.engine, published.append), 1)
        self.assertEqual(published, [job])
        self.assertEqual(publish_pending(self.engine, published.append), 0)
        self.assertTrue(run_job(self.engine, job, storage=self.storage, embed=vectors))
        self.assertFalse(run_job(self.engine, job, storage=self.storage, embed=vectors))
        self.assertEqual(self.document(doc)["status"], "READY")
        self.assertEqual(self.document(doc)["page_count"], 2)
        with Session(self.engine) as db:
            chunks = db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc)
                .order_by(DocumentChunk.chunk_index)
            ).all()
            self.assertEqual([chunk.page_number for chunk in chunks], [1, 2])
            self.assertIn("citations", chunks[1].content)
            self.assertEqual(len(chunks[0].embedding), 384)
            self.assertEqual(db.get_one(ProcessingJob, job).attempts, 1)

    def test_empty_pdf_fails_with_safe_reason_and_manual_retry_creates_a_job(self):
        doc, job = self.upload("")
        self.assertFalse(run_job(self.engine, job, storage=self.storage, embed=vectors))
        self.assertEqual(self.document(doc)["status"], "FAILED")
        self.assertEqual(self.document(doc)["processing_error"], "NO_EXTRACTABLE_TEXT")
        response = self.client.post(f"{BASE}/{doc}/retry", headers=MUTATION)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "UPLOADED")
        self.assertIsNone(response.json()["processing_error"])
        with Session(self.engine) as db:
            jobs = db.scalars(
                select(ProcessingJob).where(ProcessingJob.document_id == doc)
            ).all()
            self.assertCountEqual([row.status for row in jobs], ["PENDING", "FAILED"])

    def test_transient_failures_stop_after_three_attempts(self):
        doc, job = self.upload("The embedding service can be unavailable.")

        def failing_embedding(_texts):
            raise TimeoutError()

        for expected in (1, 2, 3):
            self.assertFalse(
                run_job(self.engine, job, storage=self.storage, embed=failing_embedding)
            )
            with Session(self.engine) as db, db.begin():
                row = db.get_one(ProcessingJob, job)
                self.assertEqual(row.attempts, expected)
                self.assertEqual(row.status, "PENDING" if expected < 3 else "FAILED")
                if expected < 3:
                    row.available_at = datetime.now(UTC) - timedelta(seconds=1)
        self.assertEqual(
            self.document(doc)["processing_error"], "INGESTION_UNAVAILABLE"
        )

    def test_abandoned_lease_cannot_overwrite_later_attempt(self):
        doc, job = self.upload("A recovered job keeps the latest result.")
        old = claim(self.engine, job)
        self.assertIsNotNone(old)
        self.assertEqual(self.document(doc)["status"], "PROCESSING")
        with Session(self.engine) as db, db.begin():
            db.get_one(ProcessingJob, job).lease_until = datetime.now(UTC) - timedelta(
                seconds=1
            )
        self.assertEqual(recover_expired(self.engine), 1)
        with Session(self.engine) as db, db.begin():
            db.get_one(ProcessingJob, job).available_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
        self.assertTrue(run_job(self.engine, job, storage=self.storage, embed=vectors))
        self.assertFalse(
            complete(
                self.engine, old, 1, [TextChunk(1, "stale output")], vectors(["x"])
            )
        )
        with Session(self.engine) as db:
            chunk = db.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == doc)
            ).one()
            self.assertIn("latest result", chunk.content)

    def test_deletion_during_indexing_prevents_new_chunks(self):
        doc, job = self.upload("Deleted documents must stay deleted.")

        def deleting_embedding(texts):
            self.assertEqual(
                self.client.delete(f"{BASE}/{doc}", headers=MUTATION).status_code, 202
            )
            return vectors(texts)

        self.assertFalse(
            run_job(self.engine, job, storage=self.storage, embed=deleting_embedding)
        )
        with Session(self.engine) as db:
            self.assertIsNone(db.get(Document, doc))
            self.assertIsNone(db.get(ProcessingJob, job))
            self.assertIsNone(
                db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc))
            )
