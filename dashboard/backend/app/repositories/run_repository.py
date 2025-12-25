"""Repository for workflow run data access."""

from datetime import datetime

from pyworkflow.engine.events import Event
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import (
    RunStatus,
    WorkflowRun,
)


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
        query: str | None = None,
        status: RunStatus | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[WorkflowRun], str | None]:
        """List workflow runs with optional filtering and cursor-based pagination.

        Args:
            query: Case-insensitive search in workflow name and input kwargs.
            status: Filter by run status.
            start_time: Filter runs started at or after this time.
            end_time: Filter runs started before this time.
            limit: Maximum number of results.
            cursor: Run ID to start after (for pagination).

        Returns:
            Tuple of (list of workflow runs, next_cursor or None).
        """
        return await self.storage.list_runs(
            query=query,
            status=status,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            cursor=cursor,
        )

    async def get_run(self, run_id: str) -> WorkflowRun | None:
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
        event_types: list[str] | None = None,
    ) -> list[Event]:
        """Get all events for a workflow run.

        Args:
            run_id: The run ID.
            event_types: Optional filter by event types.

        Returns:
            List of events ordered by sequence.
        """
        return await self.storage.get_events(run_id, event_types=event_types)
