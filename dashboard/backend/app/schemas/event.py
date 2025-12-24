"""Event response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EventResponse(BaseModel):
    """Response model for a workflow event."""

    event_id: str
    run_id: str
    type: str
    timestamp: datetime
    sequence: int | None = None
    data: dict[str, Any] = {}


class EventListResponse(BaseModel):
    """Response model for listing events."""

    items: list[EventResponse]
    count: int
