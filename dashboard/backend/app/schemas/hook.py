"""Hook response schemas."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class HookResponse(BaseModel):
    """Response model for a hook."""

    hook_id: str
    run_id: str
    name: Optional[str] = None
    status: str
    created_at: datetime
    received_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    has_payload: bool = False


class HookListResponse(BaseModel):
    """Response model for listing hooks."""

    items: List[HookResponse]
    count: int
