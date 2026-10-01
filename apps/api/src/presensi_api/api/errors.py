from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from presensi_api.api.v1.schemas.common import ApiError, ErrorDetail, ErrorEnvelope

ERROR_STATUS: dict[int, tuple[str, str]] = {
    400: ("bad_request", "The request could not be processed."),
    401: ("unauthorized", "Authentication is required."),
    403: ("forbidden", "You are not allowed to perform this action."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "This method is not allowed for the resource."),
    409: ("conflict", "The request conflicts with the current resource state."),
    413: ("file_too_large", "The uploaded file exceeds the allowed size."),
    415: (
        "unsupported_media_type",
        "The file extension or media type is not supported.",
    ),
    422: ("validation_error", "Request validation failed."),
    429: ("rate_limit_exceeded", "Too many requests."),
    500: ("internal_error", "An unexpected server error occurred."),
    501: ("not_implemented", "This API operation is not implemented yet."),
    503: ("service_unavailable", "The service is temporarily unavailable."),
}

OPENAPI_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope, "description": message}
    for status, (_, message) in ERROR_STATUS.items()
    if status not in {500, 501}
}
OPENAPI_ERROR_RESPONSES[500] = {
    "model": ErrorEnvelope,
    "description": ERROR_STATUS[500][1],
}
OPENAPI_ERROR_RESPONSES[501] = {
    "model": ErrorEnvelope,
    "description": ERROR_STATUS[501][1],
}


class ApiProblem(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorEnvelope(error=ApiError(code=code, message=message, details=details))
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=headers,
    )


async def api_problem_handler(_: Request, exc: ApiProblem) -> JSONResponse:
    return _error_response(exc.status_code, exc.code, exc.message, exc.details)


async def http_exception_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code, message = ERROR_STATUS.get(
        exc.status_code, ("request_error", "The request could not be processed.")
    )
    return _error_response(exc.status_code, code, message, headers=exc.headers)


async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        ErrorDetail(
            field=".".join(str(part) for part in error["loc"]),
            message=error["msg"],
            code=error["type"],
        )
        for error in exc.errors()
    ]
    return _error_response(
        422, "validation_error", ERROR_STATUS[422][1], details=details
    )


async def unexpected_exception_handler(_: Request, __: Exception) -> JSONResponse:
    return _error_response(500, *ERROR_STATUS[500])
