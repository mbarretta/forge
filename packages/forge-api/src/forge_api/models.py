"""Pydantic models for API request and response bodies."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolInfo(BaseModel):
    """Information about an available tool (returned by GET /api/tools)."""

    name: str
    description: str
    version: str
    params: list[ParamInfo]


class ParamInfo(BaseModel):
    """Parameter declaration for a tool."""

    name: str
    description: str
    type: str
    required: bool
    default: Any = None
    choices: list[str] | None = None


class JobCreateRequest(BaseModel):
    """Request body for POST /api/jobs."""

    tool: str
    args: dict[str, Any] = {}


class JobResponse(BaseModel):
    """Response body for job operations."""

    id: str
    tool: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0.0
    progress_message: str = ""
    summary: str | None = None
    data: dict[str, Any] | None = None
    artifacts: dict[str, str] | None = None
    error: str | None = None


class ProgressEvent(BaseModel):
    """WebSocket message for real-time progress updates."""

    job_id: str
    progress: float
    message: str
    status: JobStatus
