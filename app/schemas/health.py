"""Health response schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response schema for the health check endpoint."""

    status: str
    app_name: str
    environment: str


class ReadinessResponse(BaseModel):
    """Response schema for readiness checks against backing services."""

    status: str
    app_name: str
    environment: str
    checks: dict[str, str]
