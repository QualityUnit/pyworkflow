"""Hook response schemas."""

from datetime import datetime

from pydantic import BaseModel


class HookResponse(BaseModel):
    """Response model for a hook."""

    hook_id: str
    run_id: str
    name: str | None = None
    status: str
    created_at: datetime
    received_at: datetime | None = None
    expires_at: datetime | None = None
    has_payload: bool = False


class HookListResponse(BaseModel):
    """Response model for listing hooks."""

    items: list[HookResponse]
    count: int
