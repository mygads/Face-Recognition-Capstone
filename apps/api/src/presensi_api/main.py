import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from presensi_api.api.errors import (
    ApiProblem,
    api_problem_handler,
    http_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
)
from presensi_api.api.security.request_rate_limit import SlidingWindowRateLimiter
from presensi_api.api.v1.router import api_v1_router
from presensi_api.api.v1.schemas.health import HealthResponse
from presensi_api.db.session import get_session_factory
from presensi_api.enrollment_processing import MAX_TOTAL_CAPTURE_BYTES
from presensi_api.http_security import (
    RequestBodySizeLimitMiddleware,
    SecurityConfigurationError,
    add_restrictive_cors,
    configure_multipart_memory_only,
    parse_cors_allowed_origins,
)
from presensi_api.session_lifecycle import close_expired_sessions

logger = logging.getLogger(__name__)
_MULTIPART_OVERHEAD_BYTES = 64 * 1024


def _positive_integer_setting(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int = 10_000,
) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SecurityConfigurationError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise SecurityConfigurationError(f"{name} is outside its allowed range.")
    return value


def _run_session_auto_close_sweep() -> None:
    with get_session_factory()() as session:
        close_expired_sessions(session)


async def _session_auto_close_worker() -> None:
    while True:
        try:
            await asyncio.to_thread(_run_session_auto_close_sweep)
        except Exception:
            # Keep process health independent of migrations/database availability.
            logger.warning("Attendance session auto-close sweep failed; it will retry.")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    worker = asyncio.create_task(_session_auto_close_worker())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(
    title="Presensi Core API",
    version="1.0.0",
    description="Versioned API contract for the practicum attendance system.",
    lifespan=lifespan,
)
app.include_router(api_v1_router)
app.state.request_rate_limiter = SlidingWindowRateLimiter()
app.state.device_requests_per_minute = _positive_integer_setting(
    "PRESENSI_DEVICE_API_REQUESTS_PER_MINUTE", 120
)
app.state.enrollment_requests_per_minute = _positive_integer_setting(
    "PRESENSI_ENROLLMENT_REQUESTS_PER_MINUTE", 10
)
max_request_bytes = _positive_integer_setting(
    "PRESENSI_API_MAX_REQUEST_BYTES",
    16 * 1024 * 1024,
    minimum=MAX_TOTAL_CAPTURE_BYTES + _MULTIPART_OVERHEAD_BYTES,
    maximum=64 * 1024 * 1024,
)
configure_multipart_memory_only(max_request_bytes)
app.add_middleware(RequestBodySizeLimitMiddleware, max_bytes=max_request_bytes)
add_restrictive_cors(
    app,
    parse_cors_allowed_origins(os.getenv("PRESENSI_CORS_ALLOWED_ORIGINS")),
)


@app.exception_handler(ApiProblem)
async def handle_api_problem(request: Request, exc: ApiProblem) -> JSONResponse:
    return await api_problem_handler(request, exc)


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def handle_validation_exception(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return await validation_exception_handler(request, exc)


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    return await unexpected_exception_handler(request, exc)


@app.get(
    "/health",
    response_model=HealthResponse,
    include_in_schema=False,
    tags=["health"],
)
def infrastructure_health() -> HealthResponse:
    """Expose process health for local development and service checks."""
    return HealthResponse(status="ok")
