"""Controller for workflow run endpoints."""

from app.repositories.run_repository import RunRepository
from app.schemas.event import EventListResponse
from app.schemas.hook import HookListResponse
from app.schemas.run import RunDetailResponse, RunListResponse, StartRunRequest, StartRunResponse
from app.schemas.step import StepListResponse
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
        workflow_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> RunListResponse:
        """List workflow runs with optional filtering.

        Args:
            workflow_name: Filter by workflow name.
            status: Filter by status.
            limit: Maximum results.
            offset: Skip count.

        Returns:
            RunListResponse with matching runs.
        """
        return await self.service.list_runs(
            workflow_name=workflow_name,
            status=status,
            limit=limit,
            offset=offset,
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
