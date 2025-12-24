"""Step execution response schemas."""

from datetime import datetime

from pydantic import BaseModel


class StepResponse(BaseModel):
    """Response model for a step execution."""

    step_id: str
    run_id: str
    step_name: str
    status: str
    attempt: int = 1
    max_retries: int = 3
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    error: str | None = None


class StepListResponse(BaseModel):
    """Response model for listing steps."""

    items: list[StepResponse]
    count: int
