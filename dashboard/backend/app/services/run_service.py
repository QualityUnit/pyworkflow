"""Service layer for workflow run operations."""

import json
from datetime import UTC, datetime

from app.repositories.run_repository import RunRepository
from app.schemas.event import EventListResponse, EventResponse
from app.schemas.hook import HookListResponse, HookResponse
from app.schemas.run import RunDetailResponse, RunListResponse, RunResponse
from app.schemas.step import StepListResponse, StepResponse
from pyworkflow.storage.schemas import RunStatus


class RunService:
    """Service for workflow run-related business logic."""

    def __init__(self, repository: RunRepository):
        """Initialize with run repository.

        Args:
            repository: RunRepository instance.
        """
        self.repository = repository

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
            status: Filter by status string.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            RunListResponse with list of runs.
        """
        status_enum = RunStatus(status) if status else None

        runs = await self.repository.list_runs(
            workflow_name=workflow_name,
            status=status_enum,
            limit=limit,
            offset=offset,
        )

        items = [self._run_to_response(run) for run in runs]

        return RunListResponse(
            items=items,
            count=len(items),
            limit=limit,
            offset=offset,
        )

    async def get_run(self, run_id: str) -> RunDetailResponse | None:
        """Get detailed information about a workflow run.

        Args:
            run_id: The run ID.

        Returns:
            RunDetailResponse if found, None otherwise.
        """
        run = await self.repository.get_run(run_id)

        if run is None:
            return None

        return self._run_to_detail_response(run)

    async def get_events(self, run_id: str) -> EventListResponse:
        """Get all events for a workflow run.

        Args:
            run_id: The run ID.

        Returns:
            EventListResponse with list of events.
        """
        events = await self.repository.get_events(run_id)

        items = [
            EventResponse(
                event_id=event.event_id,
                run_id=event.run_id,
                type=event.type.value,
                timestamp=event.timestamp,
                sequence=event.sequence,
                data=event.data,
            )
            for event in events
        ]

        return EventListResponse(
            items=items,
            count=len(items),
        )

    async def get_steps(self, run_id: str) -> StepListResponse:
        """Get all steps for a workflow run.

        Args:
            run_id: The run ID.

        Returns:
            StepListResponse with list of steps.
        """
        steps = await self.repository.list_steps(run_id)

        items = [
            StepResponse(
                step_id=step.step_id,
                run_id=step.run_id,
                step_name=step.step_name,
                status=step.status.value,
                attempt=step.attempt,
                max_retries=step.max_retries,
                created_at=step.created_at,
                started_at=step.started_at,
                completed_at=step.completed_at,
                duration_seconds=self._calculate_duration(step.started_at, step.completed_at),
                error=step.error,
            )
            for step in steps
        ]

        return StepListResponse(
            items=items,
            count=len(items),
        )

    async def get_hooks(self, run_id: str) -> HookListResponse:
        """Get all hooks for a workflow run.

        Args:
            run_id: The run ID.

        Returns:
            HookListResponse with list of hooks.
        """
        hooks = await self.repository.list_hooks(run_id=run_id)

        items = [
            HookResponse(
                hook_id=hook.hook_id,
                run_id=hook.run_id,
                name=hook.name,
                status=hook.status.value,
                created_at=hook.created_at,
                received_at=hook.received_at,
                expires_at=hook.expires_at,
                has_payload=hook.payload is not None,
            )
            for hook in hooks
        ]

        return HookListResponse(
            items=items,
            count=len(items),
        )

    def _run_to_response(self, run) -> RunResponse:
        """Convert WorkflowRun to RunResponse.

        Args:
            run: WorkflowRun instance.

        Returns:
            RunResponse instance.
        """
        return RunResponse(
            run_id=run.run_id,
            workflow_name=run.workflow_name,
            status=run.status.value,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            duration_seconds=self._calculate_duration(run.started_at, run.completed_at),
            error=run.error,
            recovery_attempts=run.recovery_attempts,
        )

    def _run_to_detail_response(self, run) -> RunDetailResponse:
        """Convert WorkflowRun to RunDetailResponse.

        Args:
            run: WorkflowRun instance.

        Returns:
            RunDetailResponse instance.
        """
        # Parse JSON strings for input/result
        input_args = self._safe_json_parse(run.input_args)
        input_kwargs = self._safe_json_parse(run.input_kwargs)
        result = self._safe_json_parse(run.result) if run.result else None

        return RunDetailResponse(
            run_id=run.run_id,
            workflow_name=run.workflow_name,
            status=run.status.value,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            duration_seconds=self._calculate_duration(run.started_at, run.completed_at),
            error=run.error,
            recovery_attempts=run.recovery_attempts,
            input_args=input_args,
            input_kwargs=input_kwargs,
            result=result,
            metadata=run.metadata,
            max_duration=run.max_duration,
            max_recovery_attempts=run.max_recovery_attempts,
        )

    def _calculate_duration(
        self,
        started_at: datetime | None,
        completed_at: datetime | None,
    ) -> float | None:
        """Calculate duration in seconds.

        Args:
            started_at: Start timestamp.
            completed_at: Completion timestamp.

        Returns:
            Duration in seconds, or None if not calculable.
        """
        if started_at is None:
            return None

        end_time = completed_at or datetime.now(UTC)

        # Handle timezone-naive datetimes
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=UTC)

        return (end_time - started_at).total_seconds()

    def _safe_json_parse(self, value: str | None):
        """Safely parse a JSON string.

        Args:
            value: JSON string or None.

        Returns:
            Parsed value or the original string if parsing fails.
        """
        if value is None:
            return None

        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
