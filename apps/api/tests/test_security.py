import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest import TestCase, skipUnless
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import database_engine
from app.errors import APIError
from app.main import app
from app.models import RequestLimit
from app.rate_limit import enforce


class BrowserHeadersTest(TestCase):
    def test_browser_security_headers(self):
        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["referrer-policy"], "no-referrer")
            self.assertIn(
                "frame-ancestors 'none'", response.headers["content-security-policy"]
            )


@skipUnless(os.environ.get("DOCMIND_TEST_DATABASE_URL"), "requires migrated PostgreSQL")
class RequestLimitsTest(TestCase):
    def setUp(self):
        os.environ["DOCMIND_DATABASE_URL"] = os.environ["DOCMIND_TEST_DATABASE_URL"]
        self.engine = database_engine()

    def test_atomic_parallel_limit_and_expiry(self):
        subject = uuid4().hex

        def attempt(_index):
            with Session(self.engine) as db:
                try:
                    enforce(db, "test-parallel", subject, 4, 60)
                    return 200
                except APIError as exc:
                    return exc.status

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(12)))
        self.assertEqual(results.count(200), 4)
        self.assertEqual(results.count(429), 8)

        with Session(self.engine) as db, db.begin():
            row = db.get_one(
                RequestLimit, ("test-parallel", sha256(subject.encode()).hexdigest())
            )
            self.assertEqual(row.hits, 4)
            self.assertNotEqual(row.subject, subject)
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        self.assertEqual(attempt(0), 200)

    def test_login_throttling_returns_problem_and_retry_after(self):
        with TestClient(app, base_url="https://testserver") as client:
            credentials = {
                "email": f"{uuid4().hex}@example.com",
                "password": "a wrong local password",
            }
            for _ in range(5):
                result = client.post(
                    "/api/v1/auth/login",
                    json=credentials,
                    headers={"X-DocMind-Request": "1"},
                )
                self.assertEqual(result.status_code, 401, result.text)
            limited = client.post(
                "/api/v1/auth/login",
                json=credentials,
                headers={"X-DocMind-Request": "1"},
            )
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(limited.json()["error_code"], "RATE_LIMITED")
            self.assertGreater(int(limited.headers["retry-after"]), 0)
            self.assertEqual(limited.headers["cache-control"], "no-store")
