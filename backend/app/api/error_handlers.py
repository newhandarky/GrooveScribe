from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.core.errors import (
    ApiErrorException,
    ErrorCode,
    api_error_from_exception,
    build_error_payload,
    status_code_for_error,
)
from app.storage.errors import StorageError


def _error_response(
    code: str | ErrorCode,
    *,
    status_code: int | None = None,
    message: str | None = None,
    retriable: bool | None = None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code_for_error(code, status_code),
        content=build_error_payload(
            code,
            message=message,
            retriable=retriable,
            details=details,
        ),
    )


async def api_error_exception_handler(request: Request, exc: ApiErrorException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


async def storage_exception_handler(request: Request, exc: StorageError) -> JSONResponse:
    api_error = api_error_from_exception(exc)
    return JSONResponse(status_code=api_error.status_code, content=api_error.to_payload())


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = {"validation_errors": exc.errors()}
    return _error_response(ErrorCode.VALIDATION_ERROR, details=details)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return _error_response(
            ErrorCode.JOB_NOT_FOUND,
            status_code=404,
            message="找不到指定的 API 資源。",
        )

    if 400 <= exc.status_code < 500:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            status_code=exc.status_code,
            message=str(exc.detail) if exc.detail else None,
        )

    return _error_response(ErrorCode.INTERNAL_SERVER_ERROR)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _error_response(ErrorCode.INTERNAL_SERVER_ERROR)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiErrorException, api_error_exception_handler)
    app.add_exception_handler(StorageError, storage_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
