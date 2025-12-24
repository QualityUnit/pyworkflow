"""Service layer for workflow operations."""

from typing import List, Optional

from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.workflow import WorkflowResponse, WorkflowListResponse


class WorkflowService:
    """Service for workflow-related business logic."""

    def __init__(self, repository: WorkflowRepository):
        """Initialize with workflow repository.

        Args:
            repository: WorkflowRepository instance.
        """
        self.repository = repository

    def list_workflows(self) -> WorkflowListResponse:
        """Get all registered workflows.

        Returns:
            WorkflowListResponse with list of workflows.
        """
        workflows = self.repository.list_all()

        items = [
            WorkflowResponse(
                name=name,
                max_duration=metadata.max_duration,
                metadata=metadata.metadata or {},
            )
            for name, metadata in workflows.items()
        ]

        return WorkflowListResponse(
            items=items,
            count=len(items),
        )

    def get_workflow(self, name: str) -> Optional[WorkflowResponse]:
        """Get a specific workflow by name.

        Args:
            name: Workflow name.

        Returns:
            WorkflowResponse if found, None otherwise.
        """
        metadata = self.repository.get_by_name(name)

        if metadata is None:
            return None

        return WorkflowResponse(
            name=metadata.name,
            max_duration=metadata.max_duration,
            metadata=metadata.metadata or {},
        )
