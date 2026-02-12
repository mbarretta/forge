"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from forge_api.config import Settings
from forge_api.routes import health, jobs, tools


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle.

    Creates and tears down the Redis connection pool used for
    job status and progress pub/sub.
    """
    import redis.asyncio as aioredis

    settings: Settings = app.state.settings
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    yield

    await app.state.redis.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional settings override (useful for testing).

    Returns:
        Configured FastAPI app.
    """
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="FORGE API",
        description="Chainguard Field Engineering Toolkit",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = settings

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    prefix = settings.api_prefix
    app.include_router(health.router, tags=["health"])
    app.include_router(tools.router, prefix=prefix, tags=["tools"])
    app.include_router(jobs.router, prefix=prefix, tags=["jobs"])

    return app
