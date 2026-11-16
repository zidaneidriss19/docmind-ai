import os
from unittest import TestCase, skipUnless
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import database_engine
from app.main import app
from app.models import User

MUTATION = {"X-DocMind-Request": "1"}
PASSWORD = "a long local test password"


@skipUnless(os.environ.get("DOCMIND_TEST_DATABASE_URL"), "requires migrated PostgreSQL")
class AuthTest(TestCase):
    def setUp(self):
        os.environ["DOCMIND_DATABASE_URL"] = os.environ["DOCMIND_TEST_DATABASE_URL"]
        self.email = f"{uuid4().hex}@example.com"
        self.client = TestClient(app, base_url="https://testserver")
        self.addCleanup(self.client.close)
        self.addCleanup(self.remove_user)

    def remove_user(self):
        with Session(database_engine()) as db, db.begin():
            db.execute(delete(User).where(User.email == self.email))

    def test_authentication_lifecycle(self):
        credentials = {"email": self.email.upper(), "password": PASSWORD}
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)
        self.assertEqual(
            self.client.post("/api/v1/auth/register", json=credentials).status_code, 403
        )

        registration = self.client.post(
            "/api/v1/auth/register", json=credentials, headers=MUTATION
        )
        self.assertEqual(registration.status_code, 201, registration.text)
        self.assertEqual(registration.json()["email"], self.email)
        self.assertNotIn("password_hash", registration.json())
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/register", json=credentials, headers=MUTATION
            ).status_code,
            409,
        )

        login = self.client.post(
            "/api/v1/auth/login", json=credentials, headers=MUTATION
        )
        self.assertEqual(login.status_code, 200, login.text)
        for cookie in login.headers.get_list("set-cookie"):
            self.assertIn("HttpOnly", cookie)
            self.assertIn("Secure", cookie)
            self.assertIn("SameSite=strict", cookie)
        self.assertEqual(
            self.client.get("/api/v1/users/me").json()["email"], self.email
        )

        previous = self.client.cookies["docmind_refresh"]
        refreshed = self.client.post("/api/v1/auth/refresh", headers=MUTATION)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertNotEqual(self.client.cookies["docmind_refresh"], previous)
        with TestClient(app, base_url="https://testserver") as old_client:
            old_client.cookies.set("docmind_refresh", previous)
            self.assertEqual(
                old_client.post("/api/v1/auth/refresh", headers=MUTATION).status_code,
                401,
            )

        current = self.client.cookies["docmind_access"]
        self.assertEqual(
            self.client.post("/api/v1/auth/logout", headers=MUTATION).status_code, 204
        )
        self.client.cookies.set("docmind_access", current)
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)

    def test_invalid_password_and_validation_are_safe(self):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": PASSWORD},
            headers=MUTATION,
        )
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            "/api/v1/auth/register",
            json={"email": self.email, "password": "too-short"},
            headers=MUTATION,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["content-type"], "application/problem+json")
        self.assertEqual(response.json()["error_code"], "VALIDATION_ERROR")
        self.assertEqual(
            response.json()["request_id"], response.headers["x-request-id"]
        )
        self.assertNotIn("too-short", response.text)
