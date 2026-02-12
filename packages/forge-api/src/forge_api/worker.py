"""ARQ worker that executes tool plugins as async jobs.

Start with:
    arq forge_api.worker.WorkerSettings
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from arq.connections import ArqRedis, RedisSettings

from forge_core.auth import get_chainctl_token
from forge_core.context import ExecutionContext
from forge_core.plugin import ResultStatus
from forge_core.registry import discover_plugins

logger = logging.getLogger(__name__)

# Redis key prefixes (must match routes/jobs.py)
JOB_KEY = "forge:job:"
JOB_PROGRESS = "forge:progress:"


async def run_tool(
    ctx: dict[str, Any],
    job_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
) -> None:
    """ARQ task function: run a tool plugin.

    Called by the ARQ worker when a job is dequeued from Redis.

    Args:
        ctx: ARQ worker context (contains 'redis' connection).
        job_id: Unique job identifier.
        tool_name: Name of the tool plugin to run.
        tool_args: Arguments to pass to plugin.run().
    """
    redis: ArqRedis = ctx["redis"]

    # Mark job as running
    now = datetime.now(timezone.utc).isoformat()
    await redis.hset(
        f"{JOB_KEY}{job_id}",
        mapping={
            "status": "running",
            "started_at": now,
        },
    )

    # Load plugin
    plugins = discover_plugins()
    plugin = plugins.get(tool_name)
    if plugin is None:
        await _fail_job(redis, job_id, f"Plugin '{tool_name}' not found")
        return

    # Build progress callback that publishes to Redis
    async def _publish_progress(fraction: float, message: str) -> None:
        event = {
            "job_id": job_id,
            "progress": fraction,
            "message": message,
            "status": "running",
        }
        await redis.publish(f"{JOB_PROGRESS}{job_id}", json.dumps(event))
        await redis.hset(
            f"{JOB_KEY}{job_id}",
            mapping={
                "progress": str(fraction),
                "progress_message": message,
            },
        )

    # Because plugin.run() is synchronous and may use threading internally,
    # we need a sync-to-async bridge for the progress callback.
    loop = asyncio.get_event_loop()

    def sync_progress(fraction: float, message: str) -> None:
        asyncio.run_coroutine_threadsafe(_publish_progress(fraction, message), loop)

    # Set up cancellation listener
    cancel_event = threading.Event()

    async def _listen_for_cancel() -> None:
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"forge:cancel:{job_id}")
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                cancel_event.set()
                break
        await pubsub.unsubscribe(f"forge:cancel:{job_id}")
        await pubsub.aclose()

    cancel_task = asyncio.create_task(_listen_for_cancel())

    # Get auth token
    try:
        auth_token = get_chainctl_token()
    except RuntimeError as e:
        await _fail_job(redis, job_id, str(e))
        cancel_task.cancel()
        return

    # Build execution context
    exec_ctx = ExecutionContext(
        auth_token=auth_token,
        on_progress=sync_progress,
        cancel_event=cancel_event,
    )

    # Run the plugin in a thread to avoid blocking the async event loop
    try:
        result = await asyncio.to_thread(plugin.run, tool_args, exec_ctx)
    except Exception as e:
        logger.exception("Plugin '%s' raised an exception", tool_name)
        await _fail_job(redis, job_id, str(e))
        cancel_task.cancel()
        return

    cancel_task.cancel()

    # Store result
    completed_at = datetime.now(timezone.utc).isoformat()
    status = "completed" if result.status == ResultStatus.SUCCESS else "failed"

    await redis.hset(
        f"{JOB_KEY}{job_id}",
        mapping={
            "status": status,
            "completed_at": completed_at,
            "progress": "1.0",
            "progress_message": "Done",
            "summary": result.summary,
            "result_data": json.dumps(result.data),
            "artifacts": json.dumps(result.artifacts),
        },
    )

    # Publish terminal event
    await redis.publish(
        f"{JOB_PROGRESS}{job_id}",
        json.dumps(
            {
                "job_id": job_id,
                "progress": 1.0,
                "message": result.summary,
                "status": status,
            }
        ),
    )


async def _fail_job(redis: ArqRedis, job_id: str, error: str) -> None:
    """Mark a job as failed."""
    await redis.hset(
        f"{JOB_KEY}{job_id}",
        mapping={
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
        },
    )
    await redis.publish(
        f"{JOB_PROGRESS}{job_id}",
        json.dumps(
            {
                "job_id": job_id,
                "progress": 0.0,
                "message": error,
                "status": "failed",
            }
        ),
    )


async def startup(ctx: dict[str, Any]) -> None:
    """ARQ worker startup hook."""
    logger.info("FORGE worker starting up")


async def shutdown(ctx: dict[str, Any]) -> None:
    """ARQ worker shutdown hook."""
    logger.info("FORGE worker shutting down")


class WorkerSettings:
    """ARQ worker configuration.

    Start the worker with:
        arq forge_api.worker.WorkerSettings
    """

    functions = [run_tool]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings()  # defaults to localhost:6379
    max_jobs = 10  # concurrent jobs per worker process
    job_timeout = 600  # 10 minutes
