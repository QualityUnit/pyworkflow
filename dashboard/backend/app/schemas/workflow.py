"""Workflow-related response schemas."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class WorkflowResponse(BaseModel):
    """Response model for a registered workflow."""

    name: str
    max_duration: Optional[str] = None
    metadata: Dict[str, Any] = {}


class WorkflowListResponse(BaseModel):
    """Response model for listing workflows."""

    items: List[WorkflowResponse]
    count: int
