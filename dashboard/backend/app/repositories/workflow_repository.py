"""Repository for workflow metadata access."""

from typing import Dict, Optional

from pyworkflow import list_workflows, get_workflow
from pyworkflow.core.registry import WorkflowMetadata


class WorkflowRepository:
    """Repository for accessing registered workflow metadata."""

    def list_all(self) -> Dict[str, WorkflowMetadata]:
        """Get all registered workflows.

        Returns:
            Dictionary mapping workflow names to their metadata.
        """
        return list_workflows()

    def get_by_name(self, name: str) -> Optional[WorkflowMetadata]:
        """Get a specific workflow by name.

        Args:
            name: The workflow name.

        Returns:
            WorkflowMetadata if found, None otherwise.
        """
        return get_workflow(name)
