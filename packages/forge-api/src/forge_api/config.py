"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """FORGE API settings.

    All values can be overridden via environment variables with the
    FORGE_ prefix. Example: FORGE_REDIS_URL=redis://my-redis:6379
    """

    redis_url: str = "redis://localhost:6379"
    cors_origins: list[str] = ["http://localhost:5173"]  # Vite dev server
    api_prefix: str = "/api"
    job_timeout_seconds: int = 600  # 10 minutes max per job
    job_result_ttl_seconds: int = 3600  # keep results for 1 hour

    model_config = {"env_prefix": "FORGE_"}
