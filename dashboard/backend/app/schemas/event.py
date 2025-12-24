"""Event response schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class EventResponse(BaseModel):
    """Response model for a workflow event."""

    event_id: str
    run_id: str
    type: str
    timestamp: datetime
    sequence: Optional[int] = None
    data: Dict[str, Any] = {}


class EventListResponse(BaseModel):
    """Response model for listing events."""

    items: List[EventResponse]
    count: int
