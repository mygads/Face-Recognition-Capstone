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

app = FastAPI(
    title="Presensi Core API",
    version="1.0.0",
    description="Versioned API contract for the practicum attendance system.",
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
