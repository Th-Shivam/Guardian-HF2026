"""Service metadata and health endpoints."""

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas.health import HealthResponse, ServiceInfo

router = APIRouter()


@router.get("/", response_model=ServiceInfo, summary="Service metadata")
def read_root(settings: Settings = Depends(get_settings)) -> ServiceInfo:
    """Identify the running service."""
    return ServiceInfo(
        name=settings.project_name,
        description=settings.description,
        version=settings.version,
        docs_url="/docs",
    )


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Report that the API is up. Used by tests, Docker and uptime checks."""
    return HealthResponse(status="ok", env=settings.env, version=settings.version)
