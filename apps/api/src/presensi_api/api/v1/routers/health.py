from fastapi import APIRouter

from presensi_api.api.v1.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check API process health",
)
def health() -> HealthResponse:
    """Return process health without depending on database availability."""
    return HealthResponse(status="ok")
