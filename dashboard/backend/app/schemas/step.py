"""Step execution response schemas."""

from datetime import datetime
from typing import List, Optional
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
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


class StepListResponse(BaseModel):
    """Response model for listing steps."""

    items: List[StepResponse]
    count: int
