from typing import Literal

from fastapi import FastAPI
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
