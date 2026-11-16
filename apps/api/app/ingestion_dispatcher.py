import argparse
import logging
from time import monotonic, sleep
from uuid import UUID

from kombu.exceptions import OperationalError
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.celery_app import celery
from app.database import database_engine
from app.ingestion import publish_pending, recover_expired
from app.ingestion_queue import TASK_NAME, PublishError
from app.rate_limit import prune_limits

logger = logging.getLogger(__name__)


def send_job(job_id: UUID) -> None:
    try:
        celery.send_task(TASK_NAME, args=[str(job_id)], retry=False)
    except (OperationalError, RedisError) as exc:
        raise PublishError("Redis could not accept the ingestion job") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish durable ingestion jobs to Celery."
    )
    parser.add_argument(
        "--once", action="store_true", help="Dispatch a single batch then exit."
    )
    once = parser.parse_args().once
    logging.basicConfig(level=logging.INFO)
    engine = database_engine()
    next_cleanup = 0.0
    try:
        while True:
            try:
                if monotonic() >= next_cleanup:
                    with Session(engine) as db:
                        prune_limits(db)
                    next_cleanup = monotonic() + 1800
                recover_expired(engine)
                publish_pending(engine, send_job)
            except SQLAlchemyError as exc:
                logger.warning("Ingestion database unavailable: %s", type(exc).__name__)
                if once:
                    return 1
            if once:
                return 0
            sleep(2)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
