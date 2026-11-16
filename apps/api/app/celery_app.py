from os import environ
from uuid import UUID

from celery import Celery

from app.database import database_engine
from app.ingestion import run_job
from app.ingestion_queue import TASK_NAME

celery = Celery(
    "docmind", broker=environ.get("DOCMIND_BROKER_URL", "redis://127.0.0.1:16379/0")
)
celery.conf.update(
    accept_content=["json"],
    task_serializer="json",
    task_default_queue="document_ingestion",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=5,
    broker_transport_options={"visibility_timeout": 1800, "socket_connect_timeout": 5},
)


@celery.task(name=TASK_NAME)
def ingest_document(job_id: str) -> None:
    run_job(database_engine(), UUID(job_id))
