from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from app.auth import auth, users
from app.conversations import router as conversations
from app.documents import router as documents
from app.errors import (
    APIError,
    api_error,
    database_unavailable,
    storage_unavailable,
    validation_error,
)
from app.storage import StorageError


class HealthResponse(BaseModel):
    status: Literal["ok"]


app = FastAPI(title="DocMind AI")
app.add_exception_handler(APIError, api_error)
app.add_exception_handler(RequestValidationError, validation_error)
app.add_exception_handler(OperationalError, database_unavailable)
app.include_router(auth, prefix="/api/v1")
app.include_router(users, prefix="/api/v1")
app.include_router(documents, prefix="/api/v1")
app.include_router(conversations, prefix="/api/v1")
app.add_exception_handler(StorageError, storage_unavailable)


@app.get("/health", tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.middleware("http")
async def browser_security(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    if request.url.path.startswith("/api/v1/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response
