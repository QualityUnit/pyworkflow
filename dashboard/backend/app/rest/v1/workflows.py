"""Workflow endpoints."""

from fastapi import APIRouter, HTTPException

from app.controllers.workflow_controller import WorkflowController
from app.schemas.workflow import WorkflowListResponse, WorkflowResponse

router = APIRouter()


@router.get("", response_model=WorkflowListResponse)
async def list_workflows() -> WorkflowListResponse:
    """List all registered workflows.

    Returns:
        WorkflowListResponse with all registered workflows.
    """
    controller = WorkflowController()
    return controller.list_workflows()


@router.get("/{name}", response_model=WorkflowResponse)
async def get_workflow(name: str) -> WorkflowResponse:
    """Get a specific workflow by name.

    Args:
        name: Workflow name.

    Returns:
        WorkflowResponse with workflow details.

    Raises:
        HTTPException: 404 if workflow not found.
    """
    controller = WorkflowController()
    workflow = controller.get_workflow(name)

    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")

    return workflow
