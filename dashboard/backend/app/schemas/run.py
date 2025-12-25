"""Workflow run response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RunResponse(BaseModel):
    """Response model for a workflow run."""

    run_id: str
    workflow_name: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    error: str | None = None
    recovery_attempts: int = 0


class RunDetailResponse(RunResponse):
    """Detailed response model for a workflow run."""

    input_args: Any | None = None
    input_kwargs: Any | None = None
    result: Any | None = None
    metadata: dict[str, Any] = {}
    max_duration: str | None = None
    max_recovery_attempts: int = 3


class RunListResponse(BaseModel):
    """Response model for listing runs."""

    items: list[RunResponse]
    count: int
    limit: int = 100
    next_cursor: str | None = None


class StartRunRequest(BaseModel):
    """Request model for starting a new workflow run."""

    workflow_name: str
    kwargs: dict[str, Any] = {}


class StartRunResponse(BaseModel):
    """Response model for a newly started workflow run."""

    run_id: str
    workflow_name: str
