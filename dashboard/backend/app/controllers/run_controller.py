"""Controller for workflow run endpoints."""

from typing import Optional

from pyworkflow.storage.base import StorageBackend

from app.repositories.run_repository import RunRepository
from app.services.run_service import RunService
from app.schemas.run import RunDetailResponse, RunListResponse
from app.schemas.event import EventListResponse
from app.schemas.step import StepListResponse
from app.schemas.hook import HookListResponse


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
        workflow_name: Optional[str] = None,
        status: Optional[str] = None,
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

    async def get_run(self, run_id: str) -> Optional[RunDetailResponse]:
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

    async def get_steps(self, run_id: str) -> StepListResponse:
        """Get steps for a run.

        Args:
            run_id: The run ID.

        Returns:
            StepListResponse with run steps.
        """
        return await self.service.get_steps(run_id)

    async def get_hooks(self, run_id: str) -> HookListResponse:
        """Get hooks for a run.

        Args:
            run_id: The run ID.

        Returns:
            HookListResponse with run hooks.
        """
        return await self.service.get_hooks(run_id)
