"""Local browser test server with deterministic model adapters."""

from contextlib import asynccontextmanager
from os import environ
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import database_engine
from app.ingestion import run_job
from app.main import app
from app.models import Document, ProcessingJob, User
from app.rag import NO_ANSWER, Answer

VECTOR = [1.0] + [0.0] * 383


def work(stop: Event) -> None:
    engine = database_engine()
    while not stop.wait(0.15):
        with Session(engine) as db:
            jobs = db.scalars(
                select(ProcessingJob.id)
                .where(ProcessingJob.status == "PENDING")
                .limit(10)
            ).all()
        for job in jobs:
            run_job(engine, job, embed=lambda texts: [VECTOR for _ in texts])


def answer(_question, sources):
    return (
        Answer("75 000 euros", (sources[0],), "browser-test")
        if sources
        else Answer(NO_ANSWER)
    )


def clear_browser_fixtures() -> None:
    owners = select(User.id).where(User.email.like("e2e-%@example.com"))
    with Session(database_engine()) as db, db.begin():
        db.execute(delete(Document).where(Document.owner_id.in_(owners)))
        db.execute(delete(User).where(User.id.in_(owners)))


@asynccontextmanager
async def lifespan(_app):
    url = environ.get("DOCMIND_TEST_DATABASE_URL")
    if not url or not url.endswith("/docmind_test"):
        raise RuntimeError("Browser tests require the dedicated docmind_test database.")
    with (
        TemporaryDirectory() as directory,
        patch.dict(
            environ,
            {
                "DOCMIND_DATABASE_URL": url,
                "DOCMIND_STORAGE_BACKEND": "local",
                "DOCMIND_STORAGE_DIR": directory,
                "DOCMIND_COOKIE_SECURE": "false",
            },
        ),
        patch("app.conversations.query_vector", return_value=VECTOR),
        patch("app.conversations.generate_answer", side_effect=answer),
    ):
        clear_browser_fixtures()
        stop = Event()
        thread = Thread(target=work, args=(stop,), daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=5)
            clear_browser_fixtures()


app.router.lifespan_context = lifespan
