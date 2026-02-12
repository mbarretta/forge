"""Health check endpoints for Kubernetes probes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.requests import Request

router = APIRouter()


@router.get("/healthz")
async def health() -> dict:
    """Liveness probe. Returns 200 if the process is running."""
    return {"status": "ok"}


@router.get("/readyz")
async def ready(request: Request) -> dict:
    """Readiness probe. Returns 200 if Redis is reachable."""
    try:
        redis = request.app.state.redis
        await redis.ping()
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not ready", "error": str(e)}
