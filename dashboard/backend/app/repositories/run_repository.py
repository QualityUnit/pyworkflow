"""Repository for workflow run data access."""

from typing import List, Optional

from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import (
    WorkflowRun,
    RunStatus,
    StepExecution,
    Hook,
    HookStatus,
)
from pyworkflow.engine.events import Event


class RunRepository:
    """Repository for accessing workflow run data via pyworkflow storage."""

    def __init__(self, storage: StorageBackend):
        """Initialize with a storage backend.

        Args:
            storage: PyWorkflow storage backend instance.
        """
        self.storage = storage

    async def list_runs(
        self,
        workflow_name: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[WorkflowRun]:
        """List workflow runs with optional filtering.

        Args:
            workflow_name: Filter by workflow name.
            status: Filter by run status.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of workflow runs.
        """
        return await self.storage.list_runs(
            workflow_name=workflow_name,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        """Get a workflow run by ID.

        Args:
            run_id: The run ID.

        Returns:
            WorkflowRun if found, None otherwise.
        """
        return await self.storage.get_run(run_id)

    async def get_events(
        self,
        run_id: str,
        event_types: Optional[List[str]] = None,
    ) -> List[Event]:
        """Get all events for a workflow run.

        Args:
            run_id: The run ID.
            event_types: Optional filter by event types.

        Returns:
            List of events ordered by sequence.
        """
        return await self.storage.get_events(run_id, event_types=event_types)

    async def list_steps(self, run_id: str) -> List[StepExecution]:
        """List all steps for a workflow run.

        Args:
            run_id: The run ID.

        Returns:
            List of step executions.
        """
        return await self.storage.list_steps(run_id)

    async def list_hooks(
        self,
        run_id: Optional[str] = None,
        status: Optional[HookStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Hook]:
        """List hooks with optional filtering.

        Args:
            run_id: Filter by workflow run ID.
            status: Filter by hook status.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of hooks.
        """
        return await self.storage.list_hooks(
            run_id=run_id,
            status=status,
            limit=limit,
            offset=offset,
        )
