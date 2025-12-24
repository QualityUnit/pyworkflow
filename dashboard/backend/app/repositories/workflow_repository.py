"""Repository for workflow metadata access."""

from pyworkflow import get_workflow, list_workflows
from pyworkflow.core.registry import WorkflowMetadata


class WorkflowRepository:
    """Repository for accessing registered workflow metadata."""

    def list_all(self) -> dict[str, WorkflowMetadata]:
        """Get all registered workflows.

        Returns:
            Dictionary mapping workflow names to their metadata.
        """
        return list_workflows()

    def get_by_name(self, name: str) -> WorkflowMetadata | None:
        """Get a specific workflow by name.

        Args:
            name: The workflow name.

        Returns:
            WorkflowMetadata if found, None otherwise.
        """
        return get_workflow(name)
