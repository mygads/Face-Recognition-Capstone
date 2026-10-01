import asyncio
import logging
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
from presensi_api.api.v1.router import api_v1_router
from presensi_api.api.v1.schemas.health import HealthResponse
from presensi_api.db.session import get_session_factory
from presensi_api.session_lifecycle import close_expired_sessions

logger = logging.getLogger(__name__)


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
