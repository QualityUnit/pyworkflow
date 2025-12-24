"""Workflow-related response schemas."""

from typing import Any

from pydantic import BaseModel


class WorkflowResponse(BaseModel):
    """Response model for a registered workflow."""

    name: str
    max_duration: str | None = None
    metadata: dict[str, Any] = {}


class WorkflowListResponse(BaseModel):
    """Response model for listing workflows."""

    items: list[WorkflowResponse]
    count: int
