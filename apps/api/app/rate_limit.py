from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import ceil

from fastapi import Request
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import APIError
from app.models import RequestLimit


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce(db: Session, scope: str, subject: str, limit: int, seconds: int) -> None:
    key = sha256(subject.encode()).hexdigest()
    now = func.statement_timestamp()
    expires = now + timedelta(seconds=seconds)
    expired = RequestLimit.expires_at <= now
    statement = (
        insert(RequestLimit)
        .values(scope=scope, subject=key, hits=1, expires_at=expires)
        .on_conflict_do_update(
            index_elements=[RequestLimit.scope, RequestLimit.subject],
            set_={
                "hits": case((expired, 1), else_=RequestLimit.hits + 1),
                "expires_at": case((expired, expires), else_=RequestLimit.expires_at),
            },
            where=or_(expired, RequestLimit.hits < limit),
        )
        .returning(RequestLimit.hits)
    )
    if db.scalar(statement) is not None:
        db.commit()
        return
    retry_at = db.scalar(
        select(RequestLimit.expires_at).where(
            RequestLimit.scope == scope, RequestLimit.subject == key
        )
    )
    db.commit()
    wait = (
        max(1, ceil((retry_at - datetime.now(UTC)).total_seconds()))
        if retry_at
        else seconds
    )
    raise APIError(
        429,
        "RATE_LIMITED",
        "Too many requests. Try again shortly.",
        headers={"Retry-After": str(wait)},
    )


def prune_limits(db: Session) -> None:
    db.execute(
        delete(RequestLimit).where(
            RequestLimit.expires_at < func.now() - timedelta(days=1)
        )
    )
    db.commit()
