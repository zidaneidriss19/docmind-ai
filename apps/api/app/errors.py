from http import HTTPStatus
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError


class APIError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


async def api_error(request: Request, exc: APIError) -> JSONResponse:
    request_id = f"req_{uuid4().hex}"
    return JSONResponse(
        {
            "type": "about:blank",
            "title": HTTPStatus(exc.status).phrase,
            "status": exc.status,
            "detail": exc.message,
            "instance": request.url.path,
            "error_code": exc.code,
            "request_id": request_id,
        },
        status_code=exc.status,
        media_type="application/problem+json",
        headers={
            **exc.headers,
            "Cache-Control": "no-store",
            "X-Request-ID": request_id,
        },
    )


async def validation_error(
    request: Request, _exc: RequestValidationError
) -> JSONResponse:
    return await api_error(
        request,
        APIError(422, "VALIDATION_ERROR", "Check the request fields."),
    )


async def database_unavailable(
    request: Request, _exc: OperationalError
) -> JSONResponse:
    return await api_error(
        request,
        APIError(
            503, "DATABASE_UNAVAILABLE", "Temporarily unavailable. Try again later."
        ),
    )


async def storage_unavailable(request: Request, _exc: Exception) -> JSONResponse:
    return await api_error(
        request,
        APIError(
            503, "STORAGE_UNAVAILABLE", "Document storage is temporarily unavailable."
        ),
    )
