"""Typed, PHI-free error responses (``{"error": {"code", "message", "details"}}``)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.api import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)

__all__ = ["ApiError", "install_error_handlers"]


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def _response(
    status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or []))
    return JSONResponse(
        body.model_dump(mode="json"), status_code=status_code, headers={"Cache-Control": "no-store"}
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body echoes the input, which can be patient data: keep only
        # locations and error types.
        details = [
            {"loc": [str(p) for p in err.get("loc", ())], "type": err.get("type", "")}
            for err in exc.errors()
        ]
        return _response(422, "invalid_request", "The request is not valid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _response(exc.status_code, code, "Request failed.")

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled %s", type(exc).__name__)
        return _response(500, "internal_error", "Internal error.")
