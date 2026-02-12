"""Job submission, status, and progress streaming endpoints."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.requests import Request

from forge_api.models import JobCreateRequest, JobResponse, JobStatus, ProgressEvent
from forge_core.registry import discover_plugins

router = APIRouter()

# Redis key prefixes
JOB_KEY = "forge:job:"  # Hash: job metadata
JOB_PROGRESS = "forge:progress:"  # Pub/sub channel per job


@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job(req: JobCreateRequest, request: Request) -> JobResponse:
    """Submit a new tool run as an async job.

    The job is enqueued to ARQ and executed by a worker process.
    Returns immediately with a job ID for polling or WebSocket streaming.
    """
    redis = request.app.state.redis
    settings = request.app.state.settings

    # Validate tool exists
    plugins = discover_plugins()
    if req.tool not in plugins:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {req.tool}")

    # Create job record
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    job_data = {
        "id": job_id,
        "tool": req.tool,
        "args": json.dumps(req.args),
        "status": JobStatus.QUEUED.value,
        "created_at": now.isoformat(),
        "progress": "0.0",
        "progress_message": "",
    }

    # Store in Redis
    await redis.hset(f"{JOB_KEY}{job_id}", mapping=job_data)
    await redis.expire(f"{JOB_KEY}{job_id}", settings.job_result_ttl_seconds)

    # Enqueue to ARQ
    from arq import create_pool
    from arq.connections import RedisSettings

    arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await arq_pool.enqueue_job(
        "run_tool",
        job_id,
        req.tool,
        req.args,
    )
    await arq_pool.close()

    return JobResponse(
        id=job_id,
        tool=req.tool,
        status=JobStatus.QUEUED,
        created_at=now,
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, request: Request) -> JobResponse:
    """Get current status of a job."""
    redis = request.app.state.redis
    data = await redis.hgetall(f"{JOB_KEY}{job_id}")

    if not data:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse(
        id=data["id"],
        tool=data["tool"],
        status=JobStatus(data["status"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        started_at=_parse_dt(data.get("started_at")),
        completed_at=_parse_dt(data.get("completed_at")),
        progress=float(data.get("progress", 0)),
        progress_message=data.get("progress_message", ""),
        summary=data.get("summary"),
        data=json.loads(data["result_data"]) if data.get("result_data") else None,
        artifacts=json.loads(data["artifacts"]) if data.get("artifacts") else None,
        error=data.get("error"),
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str, request: Request) -> JobResponse:
    """Request cancellation of a running job."""
    redis = request.app.state.redis

    # Signal cancellation via Redis pub/sub
    await redis.publish(f"forge:cancel:{job_id}", "cancel")
    await redis.hset(f"{JOB_KEY}{job_id}", "status", JobStatus.CANCELLED.value)

    return await get_job(job_id, request)


@router.websocket("/jobs/{job_id}/ws")
async def job_progress_ws(websocket: WebSocket, job_id: str) -> None:
    """WebSocket endpoint for real-time job progress.

    Subscribes to Redis pub/sub channel for the job and forwards
    progress events to the WebSocket client.
    """
    await websocket.accept()
    redis = websocket.app.state.redis

    pubsub = redis.pubsub()
    await pubsub.subscribe(f"{JOB_PROGRESS}{job_id}")

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            event = json.loads(message["data"])
            await websocket.send_json(event)

            # Close when job is terminal
            if event.get("status") in (
                JobStatus.COMPLETED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            ):
                break
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(f"{JOB_PROGRESS}{job_id}")
        await pubsub.aclose()


def _parse_dt(val: str | None) -> datetime | None:
    """Parse ISO datetime string or return None."""
    if val:
        return datetime.fromisoformat(val)
    return None
