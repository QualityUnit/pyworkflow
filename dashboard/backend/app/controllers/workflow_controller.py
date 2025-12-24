"""Controller for workflow endpoints."""

from typing import Optional

from app.repositories.workflow_repository import WorkflowRepository
from app.services.workflow_service import WorkflowService
from app.schemas.workflow import WorkflowResponse, WorkflowListResponse


class WorkflowController:
    """Controller handling workflow-related requests."""

    def __init__(self):
        """Initialize controller with service layer."""
        self.repository = WorkflowRepository()
        self.service = WorkflowService(self.repository)

    def list_workflows(self) -> WorkflowListResponse:
        """Get all registered workflows.

        Returns:
            WorkflowListResponse with all workflows.
        """
        return self.service.list_workflows()

    def get_workflow(self, name: str) -> Optional[WorkflowResponse]:
        """Get a specific workflow by name.

        Args:
            name: Workflow name.

        Returns:
            WorkflowResponse if found, None otherwise.
        """
        return self.service.get_workflow(name)
