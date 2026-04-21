"""Health check routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    """Return a minimal health response."""

    return {"status": "ok", "service": "schwab-api-trader"}
