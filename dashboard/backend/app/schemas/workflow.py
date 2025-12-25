"""Workflow-related response schemas."""

from typing import Any

from pydantic import BaseModel


class WorkflowParameter(BaseModel):
    """Response model for a workflow parameter."""

    name: str
    type: str  # "string", "number", "boolean", "object", "array", "any"
    required: bool
    default: Any | None = None


class WorkflowResponse(BaseModel):
    """Response model for a registered workflow."""

    name: str
    description: str | None = None
    max_duration: str | None = None
    tags: list[str] = []
    parameters: list[WorkflowParameter] = []


class WorkflowListResponse(BaseModel):
    """Response model for listing workflows."""

    items: list[WorkflowResponse]
    count: int
