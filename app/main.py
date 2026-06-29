"""FastAPI application entrypoint."""

import logging
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi import Request

from app.api.routes.auth import router as auth_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.documents import router as documents_router
from app.api.routes.document_events import router as document_events_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log one request with request ID, method, path, status, and latency."""

    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.exception(
            "request_id=%s method=%s path=%s status_code=500 duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status_code=%s duration_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(documents_router)
app.include_router(document_events_router)
app.include_router(health_router)
