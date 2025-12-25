"""Service layer for workflow run operations."""

import json
from datetime import UTC, datetime
from typing import Any

import pyworkflow
from app.repositories.run_repository import RunRepository
from app.schemas.event import EventListResponse, EventResponse
from app.schemas.run import (
    RunDetailResponse,
    RunListResponse,
    RunResponse,
    StartRunRequest,
    StartRunResponse,
)
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


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
            status: Filter by status string.
            start_time: Filter runs started at or after this time.
            end_time: Filter runs started before this time.
            limit: Maximum number of results.
            cursor: Run ID to start after (for pagination).

        Returns:
            RunListResponse with list of runs and next_cursor.
        """
        status_enum = RunStatus(status) if status else None

        runs, next_cursor = await self.repository.list_runs(
            query=query,
            status=status_enum,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            cursor=cursor,
        )

        items = [self._run_to_response(run) for run in runs]

        return RunListResponse(
            items=items,
            count=len(items),
            limit=limit,
            next_cursor=next_cursor,
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

    def _run_to_response(self, run: WorkflowRun) -> RunResponse:
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

    def _run_to_detail_response(self, run: WorkflowRun) -> RunDetailResponse:
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

    def _safe_json_parse(self, value: str | None) -> Any:
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

    async def start_run(self, request: StartRunRequest) -> StartRunResponse:
        """Start a new workflow run.

        Args:
            request: The start run request containing workflow name and kwargs.

        Returns:
            StartRunResponse with run_id and workflow_name.

        Raises:
            ValueError: If workflow not found.
        """
        # Get the workflow metadata
        workflow_meta = pyworkflow.get_workflow(request.workflow_name)
        if workflow_meta is None:
            raise ValueError(f"Workflow '{request.workflow_name}' not found")

        # Start the workflow using pyworkflow.start()
        run_id = await pyworkflow.start(
            workflow_meta.func,
            **request.kwargs,
        )

        return StartRunResponse(
            run_id=run_id,
            workflow_name=request.workflow_name,
        )
