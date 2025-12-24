"""Workflow run response schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class RunResponse(BaseModel):
    """Response model for a workflow run."""

    run_id: str
    workflow_name: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    recovery_attempts: int = 0


class RunDetailResponse(RunResponse):
    """Detailed response model for a workflow run."""

    input_args: Optional[Any] = None
    input_kwargs: Optional[Any] = None
    result: Optional[Any] = None
    metadata: Dict[str, Any] = {}
    max_duration: Optional[str] = None
    max_recovery_attempts: int = 3


class RunListResponse(BaseModel):
    """Response model for listing runs."""

    items: List[RunResponse]
    count: int
    limit: int = 100
    offset: int = 0
