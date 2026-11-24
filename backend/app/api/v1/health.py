from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.core.config import Settings
from app.db.session import get_app_settings, get_db_manager

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    app_name: str
    version: str
    environment: str
    llm_provider: str


def _build_health_response(settings: Settings) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_slug,
        app_name=settings.app_name,
        version="0.1.0",
        environment=settings.app_env,
        llm_provider=settings.llm_default_provider,
    )


@router.get("", response_model=HealthResponse)
@router.get("/live", response_model=HealthResponse)
async def health_live(settings: Settings = Depends(get_app_settings)) -> HealthResponse:
    """Return service liveness and runtime configuration summary."""
    return _build_health_response(settings)


@router.get("/ready", response_model=HealthResponse)
async def health_ready(
    request: Request,
    settings: Settings = Depends(get_app_settings),
) -> HealthResponse:
    """Verify database connectivity and return readiness status."""
    db = get_db_manager(request)
    try:
        await db.ping()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database readiness check failed.",
        ) from exc
    return _build_health_response(settings)
