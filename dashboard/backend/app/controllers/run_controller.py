"""Controller for workflow run endpoints."""

from datetime import datetime

from app.repositories.run_repository import RunRepository
from app.schemas.event import EventListResponse
from app.schemas.run import RunDetailResponse, RunListResponse, StartRunRequest, StartRunResponse
from app.services.run_service import RunService
from pyworkflow.storage.base import StorageBackend


class RunController:
    """Controller handling workflow run-related requests."""

    def __init__(self, storage: StorageBackend):
        """Initialize controller with storage backend.

        Args:
            storage: PyWorkflow storage backend.
        """
        self.repository = RunRepository(storage)
        self.service = RunService(self.repository)

    async def list_runs(
        self,
        query: str | None = None,
        status: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> RunListResponse:
        """List workflow runs with optional filtering and cursor-based pagination.

        Args:
            query: Case-insensitive search in workflow name and input kwargs.
            status: Filter by status.
            start_time: Filter runs started at or after this time.
            end_time: Filter runs started before this time.
            limit: Maximum results.
            cursor: Run ID to start after (for pagination).

        Returns:
            RunListResponse with matching runs and next_cursor.
        """
        return await self.service.list_runs(
            query=query,
            status=status,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            cursor=cursor,
        )

    async def get_run(self, run_id: str) -> RunDetailResponse | None:
        """Get detailed information about a run.

        Args:
            run_id: The run ID.

        Returns:
            RunDetailResponse if found, None otherwise.
        """
        return await self.service.get_run(run_id)

    async def get_events(self, run_id: str) -> EventListResponse:
        """Get events for a run.

        Args:
            run_id: The run ID.

        Returns:
            EventListResponse with run events.
        """
        return await self.service.get_events(run_id)

    async def start_run(self, request: StartRunRequest) -> StartRunResponse:
        """Start a new workflow run.

        Args:
            request: The start run request containing workflow name and kwargs.

        Returns:
            StartRunResponse with run_id and workflow_name.
        """
        return await self.service.start_run(request)
