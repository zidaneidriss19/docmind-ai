import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import database_engine
from app.documents import recover_storage
from app.main import app
from app.models import Document, ProcessingJob, User
from app.storage import LocalStorage, StorageError

DOCUMENTS = "/api/v1/documents"
MUTATION = {"X-DocMind-Request": "1"}


def pdf_bytes(*, encrypted=False):
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    if encrypted:
        writer.encrypt("document-test")
    writer.write(stream)
    return stream.getvalue()


@skipUnless(os.environ.get("DOCMIND_TEST_DATABASE_URL"), "requires migrated PostgreSQL")
class DocumentsTest(TestCase):
    def setUp(self):
        os.environ["DOCMIND_DATABASE_URL"] = os.environ["DOCMIND_TEST_DATABASE_URL"]
        directory = self.enterContext(TemporaryDirectory())
        self.storage = LocalStorage(Path(directory))
        self.enterContext(patch("app.documents.get_storage", return_value=self.storage))
        self.user_ids = []
        self.addCleanup(self.remove_records)
        self.owner = self.account()
        self.pdf = pdf_bytes()

    def account(self):
        client = self.enterContext(TestClient(app, base_url="https://testserver"))
        payload = {
            "email": f"{uuid4().hex}@example.com",
            "password": "a long local test password",
        }
        response = client.post("/api/v1/auth/register", json=payload, headers=MUTATION)
        self.assertEqual(response.status_code, 201, response.text)
        self.user_ids.append(UUID(response.json()["id"]))
        response = client.post("/api/v1/auth/login", json=payload, headers=MUTATION)
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def remove_records(self):
        with Session(database_engine()) as db, db.begin():
            db.execute(delete(Document).where(Document.owner_id.in_(self.user_ids)))
            db.execute(delete(User).where(User.id.in_(self.user_ids)))

    def upload(self, content=None, filename="document.pdf"):
        return self.owner.post(
            DOCUMENTS,
            files={
                "file": (
                    filename,
                    self.pdf if content is None else content,
                    "application/pdf",
                )
            },
            headers=MUTATION,
        )

    def test_upload_list_download_retry_and_delete(self):
        response = self.upload(filename="résumé.pdf")
        self.assertEqual(response.status_code, 202, response.text)
        document = response.json()
        url = f"{DOCUMENTS}/{document['id']}"
        self.assertEqual(document["status"], "UPLOADED")
        self.assertEqual(document["size_bytes"], len(self.pdf))
        self.assertNotIn("storage_key", document)
        with Session(database_engine()) as db:
            row = db.get_one(Document, UUID(document["id"]))
            self.assertEqual(row.checksum_sha256, sha256(self.pdf).hexdigest())

        self.assertEqual(self.upload().status_code, 202)
        page = self.owner.get(DOCUMENTS, params={"limit": 1}).json()
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["next_offset"], 1)
        self.assertEqual(
            self.owner.get(DOCUMENTS, params={"limit": 1, "offset": 1}).json()["items"][
                0
            ]["id"],
            document["id"],
        )
        self.assertEqual(self.owner.get(url).json(), document)
        self.assertEqual(self.owner.get(f"{url}/status").json()["status"], "UPLOADED")

        response = self.owner.get(f"{url}/file")
        self.assertEqual(response.content, self.pdf)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("no-store", response.headers["cache-control"])

        self.assertEqual(
            self.owner.post(f"{url}/retry", headers=MUTATION).status_code, 409
        )
        with Session(database_engine()) as db, db.begin():
            document_id = UUID(document["id"])
            db.get_one(Document, document_id).status = "FAILED"
            job = db.scalar(
                select(ProcessingJob).where(ProcessingJob.document_id == document_id)
            )
            job.status = "FAILED"
        self.assertEqual(
            self.owner.post(f"{url}/retry", headers=MUTATION).json()["status"],
            "UPLOADED",
        )
        self.assertEqual(self.owner.delete(url, headers=MUTATION).status_code, 202)
        self.assertEqual(self.owner.get(url).status_code, 404)

    def test_other_users_cannot_read_or_change_documents(self):
        document = self.upload().json()
        url = f"{DOCUMENTS}/{document['id']}"
        other = self.account()
        self.assertEqual(other.get(DOCUMENTS).json()["items"], [])
        for path in (url, f"{url}/status", f"{url}/file"):
            self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(other.delete(url, headers=MUTATION).status_code, 404)
        self.assertEqual(other.post(f"{url}/retry", headers=MUTATION).status_code, 404)
        with TestClient(app, base_url="https://testserver") as anonymous:
            self.assertEqual(anonymous.get(DOCUMENTS).status_code, 401)
        self.assertEqual(self.owner.delete(url).status_code, 403)

    def test_validation_and_streamed_size_limit(self):
        for content in (b"fake", b"%PDF-1.7\ninvalid", pdf_bytes(encrypted=True)):
            self.assertEqual(self.upload(content).status_code, 400)
        self.assertEqual(self.upload(filename="document.exe").status_code, 400)
        with patch("app.documents.MAX_MULTIPART_BYTES", 32):
            response = self.owner.post(
                DOCUMENTS,
                content=iter((b"x" * 20, b"x" * 20)),
                headers={
                    **MUTATION,
                    "Content-Type": "multipart/form-data; boundary=docmind",
                },
            )
            self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(self.owner.get(DOCUMENTS).json()["items"], [])

    def test_recovery_after_upload_and_delete_failures(self):
        original = self.storage.put

        def store_then_fail(key, source, size):
            original(key, source, size)
            raise StorageError("test: ambiguous write")

        with patch.object(self.storage, "put", side_effect=store_then_fail):
            self.assertEqual(self.upload().status_code, 503)
        self.assertEqual(self.owner.get(DOCUMENTS).json()["items"], [])
        with Session(database_engine()) as db, db.begin():
            row = db.scalar(
                select(Document).where(Document.owner_id == self.user_ids[0])
            )
            self.assertEqual(row.status, "UPLOADING")
            key = row.storage_key
            row.updated_at = datetime.now(UTC) - timedelta(hours=2)
        with Session(database_engine()) as db:
            self.assertEqual(recover_storage(db), (1, 0))
        self.assertFalse(self.storage.path(key).exists())

        document = self.upload().json()
        url = f"{DOCUMENTS}/{document['id']}"
        with patch.object(
            self.storage, "delete", side_effect=StorageError("test: unavailable")
        ):
            self.assertEqual(self.owner.delete(url, headers=MUTATION).status_code, 202)
            self.assertEqual(self.owner.get(url).status_code, 404)
            with Session(database_engine()) as db:
                self.assertEqual(recover_storage(db), (0, 1))
        with Session(database_engine()) as db:
            self.assertEqual(recover_storage(db), (1, 0))
            self.assertIsNone(db.get(Document, UUID(document["id"])))
