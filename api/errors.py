"""Uniform API errors."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def envelope(request: Request, status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return envelope(request, exc.status, exc.code, exc.message, exc.details)


async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return envelope(request, 422, "validation_failed", "Request validation failed", {"errors": exc.errors()[:10]})


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    return envelope(request, 500, "internal_error", "Internal server error", {"type": type(exc).__name__})
