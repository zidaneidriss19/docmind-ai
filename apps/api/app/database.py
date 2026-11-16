from collections.abc import Iterator
from functools import lru_cache
from os import environ

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session


def database_url() -> str | URL:
    if url := environ.get("DOCMIND_DATABASE_URL"):
        return url
    return URL.create(
        "postgresql+psycopg",
        username=environ.get("POSTGRES_USER", "docmind"),
        password=environ["POSTGRES_PASSWORD"],
        host="127.0.0.1",
        port=int(environ.get("POSTGRES_PORT", "5432")),
        database=environ.get("POSTGRES_DB", "docmind"),
    )


@lru_cache
def database_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True, hide_parameters=True)


def get_db() -> Iterator[Session]:
    with Session(database_engine()) as db:
        yield db
