"""Workflow-related response schemas."""

from pydantic import BaseModel


class WorkflowResponse(BaseModel):
    """Response model for a registered workflow."""

    name: str
    description: str | None = None
    max_duration: str | None = None
    tags: list[str] = []


class WorkflowListResponse(BaseModel):
    """Response model for listing workflows."""

    items: list[WorkflowResponse]
    count: int
