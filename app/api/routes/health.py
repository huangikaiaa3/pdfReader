"""Health and readiness routes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.schemas.health import HealthResponse, ReadinessResponse
from app.services.queue_service import get_redis_client

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return the basic application health status."""

    settings = get_settings()
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
    )


@router.get("/livez", response_model=HealthResponse)
def liveness_check() -> HealthResponse:
    """Return a lightweight process liveness signal."""

    return health_check()


@router.get("/readyz", response_model=ReadinessResponse)
def readiness_check() -> JSONResponse:
    """Return readiness based on required backing services."""

    settings = get_settings()
    checks = {
        "database": _check_database(),
        "redis": _check_redis(),
    }
    overall_status = "ok" if all(status == "ok" for status in checks.values()) else "degraded"
    payload = ReadinessResponse(
        status=overall_status,
        app_name=settings.app_name,
        environment=settings.environment,
        checks=checks,
    )
    return JSONResponse(status_code=200 if overall_status == "ok" else 503, content=payload.model_dump())


def _check_database() -> str:
    """Return database readiness for the current process."""

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"
    finally:
        db.close()


def _check_redis() -> str:
    """Return Redis readiness for the current process."""

    try:
        get_redis_client().ping()
        return "ok"
    except Exception:
        return "error"
