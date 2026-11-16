import json
import os
from io import BytesIO
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.chat_models import Conversation, ConversationDocument
from app.database import database_engine
from app.errors import APIError
from app.main import app
from app.models import Document, DocumentChunk, User
from app.rag import NO_ANSWER, Answer, Source, generate_answer

BASE = "/api/v1/conversations"
HEADERS = {"X-DocMind-Request": "1"}
VECTOR = [1.0] + [0.0] * 383


class OllamaTest(TestCase):
    def test_invalid_source_reference_is_rejected(self):
        source = Source(uuid4(), uuid4(), 1, "Actual context")
        model = {
            "message": {
                "content": json.dumps(
                    {
                        "supported": True,
                        "answer": "Unsupported citation",
                        "source_numbers": [42],
                    }
                )
            }
        }
        with (
            patch("app.rag.urlopen", return_value=BytesIO(json.dumps(model).encode())),
            self.assertRaises(APIError) as error,
        ):
            generate_answer("Question", [source])
        self.assertEqual(error.exception.status, 502)


@skipUnless(os.environ.get("DOCMIND_TEST_DATABASE_URL"), "requires migrated pgvector")
class ConversationTest(TestCase):
    def setUp(self):
        os.environ["DOCMIND_DATABASE_URL"] = os.environ["DOCMIND_TEST_DATABASE_URL"]
        self.engine = database_engine()
        self.owner_ids = []
        self.addCleanup(self.remove_accounts)
        self.owner, self.client = self.account()
        self.other, self.other_client = self.account()
        self.document = self.seed_document(
            self.owner, "Project Atlas costs 75,000 euros.", 2
        )
        self.secret = self.seed_document(
            self.other, "A private account has a secret.", 8
        )

    def account(self):
        client = self.enterContext(TestClient(app, base_url="https://testserver"))
        credentials = {
            "email": f"{uuid4().hex}@example.com",
            "password": "a long local test password",
        }
        response = client.post(
            "/api/v1/auth/register", json=credentials, headers=HEADERS
        )
        self.assertEqual(response.status_code, 201, response.text)
        owner = UUID(response.json()["id"])
        self.owner_ids.append(owner)
        self.assertEqual(
            client.post(
                "/api/v1/auth/login", json=credentials, headers=HEADERS
            ).status_code,
            200,
        )
        return owner, client

    def remove_accounts(self):
        with Session(self.engine) as db, db.begin():
            db.execute(
                delete(Conversation).where(Conversation.owner_id.in_(self.owner_ids))
            )
            db.execute(delete(Document).where(Document.owner_id.in_(self.owner_ids)))
            db.execute(delete(User).where(User.id.in_(self.owner_ids)))

    def seed_document(self, owner, content, page):
        document = uuid4()
        with Session(self.engine) as db, db.begin():
            db.add(
                Document(
                    id=document,
                    owner_id=owner,
                    filename="test.pdf",
                    storage_key=f"{owner}/{document}.pdf",
                    mime_type="application/pdf",
                    size_bytes=1,
                    checksum_sha256="0" * 64,
                    status="READY",
                    page_count=page,
                )
            )
            db.flush()
            db.add(
                DocumentChunk(
                    document_id=document,
                    chunk_index=0,
                    page_number=page,
                    content=content,
                    embedding=VECTOR,
                )
            )
        return document

    def create(self):
        response = self.client.post(
            BASE,
            json={"title": "Atlas", "document_ids": [str(self.document)]},
            headers=HEADERS,
        )
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["document_ids"], [str(self.document)])
        return result["id"]

    def test_cited_answer_and_history_are_private(self):
        conversation = self.create()
        url = f"{BASE}/{conversation}"
        self.assertEqual(self.other_client.get(url).status_code, 404)
        self.assertEqual(self.other_client.get(f"{url}/messages").status_code, 404)
        self.assertEqual(
            self.client.put(
                f"{url}/documents",
                json={"document_ids": [str(self.secret)]},
                headers=HEADERS,
            ).status_code,
            404,
        )
        # A faulty association cannot expose another account even if written outside the API.
        with Session(self.engine) as db, db.begin():
            db.add(
                ConversationDocument(
                    conversation_id=UUID(conversation), document_id=self.secret
                )
            )

        def answer(_question, sources):
            self.assertEqual(
                [source.document_id for source in sources], [self.document]
            )
            return Answer(
                "Le budget est de 75 000 euros.", tuple(sources), "test-model", 30, 8
            )

        with (
            patch("app.conversations.query_vector", return_value=VECTOR),
            patch("app.conversations.generate_answer", side_effect=answer),
        ):
            response = self.client.post(
                f"{url}/messages",
                json={"content": "What is the budget?"},
                headers=HEADERS,
            )
        self.assertEqual(response.status_code, 201, response.text)
        message = response.json()
        source = message["citations"][0]
        self.assertEqual(source["document_id"], str(self.document))
        self.assertEqual(source["page_number"], 2)
        self.assertIn("75,000", source["excerpt"])
        history = self.client.get(f"{url}/messages").json()
        self.assertEqual(
            [item["role"] for item in history["items"]], ["user", "assistant"]
        )
        self.assertEqual(history["items"][1], message)
        self.assertEqual(self.client.delete(url, headers=HEADERS).status_code, 204)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_unrelated_question_and_provider_failure(self):
        url = f"{BASE}/{self.create()}/messages"
        with patch(
            "app.conversations.query_vector", return_value=[0.0, 1.0] + [0.0] * 382
        ):
            response = self.client.post(
                url, json={"content": "Unrelated question"}, headers=HEADERS
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["content"], NO_ANSWER)
        self.assertEqual(response.json()["citations"], [])

        with (
            patch("app.conversations.query_vector", return_value=VECTOR),
            patch(
                "app.conversations.generate_answer",
                side_effect=APIError(503, "LLM_UNAVAILABLE", "Unavailable"),
            ),
        ):
            response = self.client.post(
                url, json={"content": "Atlas budget"}, headers=HEADERS
            )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            self.client.get(url).json()["items"][-1]["content"], "Atlas budget"
        )
