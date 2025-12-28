"""
Abstract base class for storage backends.

All storage implementations must implement this interface to ensure consistency
across different backends (File, Redis, SQLite, PostgreSQL).
"""

from abc import ABC, abstractmethod
from datetime import datetime

from pyworkflow.engine.events import Event
from pyworkflow.storage.schemas import (
    Hook,
    HookStatus,
    RunStatus,
    Schedule,
    ScheduleStatus,
    StepExecution,
    WorkflowRun,
)


class StorageBackend(ABC):
    """
    Abstract base class for workflow storage backends.

    Storage backends are responsible for:
    - Persisting workflow runs, steps
    - Managing the event log (append-only)
    - Providing query capabilities

    All methods are async to support both sync and async backends.
    """

    # Workflow Run Operations

    @abstractmethod
    async def create_run(self, run: WorkflowRun) -> None:
        """
        Create a new workflow run record.

        Args:
            run: WorkflowRun instance to persist

        Raises:
            Exception: If run_id already exists
        """
        pass

    @abstractmethod
    async def get_run(self, run_id: str) -> WorkflowRun | None:
        """
        Retrieve a workflow run by ID.

        Args:
            run_id: Unique workflow run identifier

        Returns:
            WorkflowRun if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_run_by_idempotency_key(self, key: str) -> WorkflowRun | None:
        """
        Retrieve a workflow run by idempotency key.

        Args:
            key: Idempotency key

        Returns:
            WorkflowRun if found, None otherwise
        """
        pass

    @abstractmethod
    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """
        Update workflow run status and optionally result/error.

        Args:
            run_id: Workflow run identifier
            status: New status
            result: Serialized result (if completed)
            error: Error message (if failed)
        """
        pass

    @abstractmethod
    async def update_run_recovery_attempts(
        self,
        run_id: str,
        recovery_attempts: int,
    ) -> None:
        """
        Update the recovery attempts counter for a workflow run.

        Called when a workflow is being recovered after a worker failure.

        Args:
            run_id: Workflow run identifier
            recovery_attempts: New recovery attempts count
        """
        pass

    @abstractmethod
    async def update_run_context(
        self,
        run_id: str,
        context: dict,
    ) -> None:
        """
        Update the step context for a workflow run.

        Called when set_step_context() is invoked in workflow code.
        The context is stored and can be loaded by steps running on
        remote workers.

        Args:
            run_id: Workflow run identifier
            context: Context data as a dictionary (serialized StepContext)
        """
        pass

    @abstractmethod
    async def get_run_context(self, run_id: str) -> dict:
        """
        Get the current step context for a workflow run.

        Called when a step starts execution on a remote worker to
        load the context that was set by the workflow.

        Args:
            run_id: Workflow run identifier

        Returns:
            Context data as a dictionary, or empty dict if not set
        """
        pass

    @abstractmethod
    async def list_runs(
        self,
        query: str | None = None,
        status: RunStatus | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[WorkflowRun], str | None]:
        """
        List workflow runs with optional filtering and cursor-based pagination.

        Args:
            query: Case-insensitive substring search in workflow_name and input_kwargs
            status: Filter by status
            start_time: Filter runs started at or after this time
            end_time: Filter runs started before this time
            limit: Maximum number of results
            cursor: Run ID to start after (for pagination)

        Returns:
            Tuple of (list of WorkflowRun instances, next_cursor or None if no more results)
        """
        pass

    # Event Log Operations

    @abstractmethod
    async def record_event(self, event: Event) -> None:
        """
        Record an event to the append-only event log.

        Events must be assigned a sequence number by the storage backend
        to ensure ordering.

        Args:
            event: Event to record (sequence will be assigned)
        """
        pass

    @abstractmethod
    async def get_events(
        self,
        run_id: str,
        event_types: list[str] | None = None,
    ) -> list[Event]:
        """
        Retrieve all events for a workflow run, ordered by sequence.

        Args:
            run_id: Workflow run identifier
            event_types: Optional filter by event types

        Returns:
            List of events ordered by sequence number
        """
        pass

    @abstractmethod
    async def get_latest_event(
        self,
        run_id: str,
        event_type: str | None = None,
    ) -> Event | None:
        """
        Get the latest event for a run, optionally filtered by type.

        Args:
            run_id: Workflow run identifier
            event_type: Optional event type filter

        Returns:
            Latest matching event or None
        """
        pass

    # Step Operations

    @abstractmethod
    async def create_step(self, step: StepExecution) -> None:
        """
        Create a step execution record.

        Args:
            step: StepExecution instance to persist
        """
        pass

    @abstractmethod
    async def get_step(self, step_id: str) -> StepExecution | None:
        """
        Retrieve a step execution by ID.

        Args:
            step_id: Step identifier

        Returns:
            StepExecution if found, None otherwise
        """
        pass

    @abstractmethod
    async def update_step_status(
        self,
        step_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """
        Update step execution status.

        Args:
            step_id: Step identifier
            status: New status
            result: Serialized result (if completed)
            error: Error message (if failed)
        """
        pass

    @abstractmethod
    async def list_steps(self, run_id: str) -> list[StepExecution]:
        """
        List all steps for a workflow run.

        Args:
            run_id: Workflow run identifier

        Returns:
            List of StepExecution instances
        """
        pass

    # Hook Operations

    @abstractmethod
    async def create_hook(self, hook: Hook) -> None:
        """
        Create a hook record.

        Args:
            hook: Hook instance to persist
        """
        pass

    @abstractmethod
    async def get_hook(self, hook_id: str) -> Hook | None:
        """
        Retrieve a hook by ID.

        Args:
            hook_id: Hook identifier

        Returns:
            Hook if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_hook_by_token(self, token: str) -> Hook | None:
        """
        Retrieve a hook by its token.

        Args:
            token: Hook token (composite format: run_id:hook_id)

        Returns:
            Hook if found, None otherwise
        """
        pass

    @abstractmethod
    async def update_hook_status(
        self,
        hook_id: str,
        status: HookStatus,
        payload: str | None = None,
    ) -> None:
        """
        Update hook status and optionally payload.

        Args:
            hook_id: Hook identifier
            status: New status
            payload: JSON serialized payload (if received)
        """
        pass

    @abstractmethod
    async def list_hooks(
        self,
        run_id: str | None = None,
        status: HookStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Hook]:
        """
        List hooks with optional filtering.

        Args:
            run_id: Filter by workflow run ID
            status: Filter by status
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of Hook instances
        """
        pass

    # Cancellation Flag Operations

    @abstractmethod
    async def set_cancellation_flag(self, run_id: str) -> None:
        """
        Set a cancellation flag for a workflow run.

        This flag is checked by running workflows to detect cancellation
        requests. It's used when we can't directly interrupt a running
        workflow (e.g., Celery workers).

        Args:
            run_id: Workflow run identifier
        """
        pass

    @abstractmethod
    async def check_cancellation_flag(self, run_id: str) -> bool:
        """
        Check if a cancellation flag is set for a workflow run.

        Args:
            run_id: Workflow run identifier

        Returns:
            True if cancellation is requested, False otherwise
        """
        pass

    @abstractmethod
    async def clear_cancellation_flag(self, run_id: str) -> None:
        """
        Clear the cancellation flag for a workflow run.

        Called after cancellation has been processed or if cancellation
        is no longer needed.

        Args:
            run_id: Workflow run identifier
        """
        pass

    # Continue-As-New Chain Operations

    @abstractmethod
    async def update_run_continuation(
        self,
        run_id: str,
        continued_to_run_id: str,
    ) -> None:
        """
        Update the continuation link for a workflow run.

        Called when a workflow continues as new to link the current
        run to the new run.

        Args:
            run_id: Current workflow run identifier
            continued_to_run_id: New workflow run identifier
        """
        pass

    @abstractmethod
    async def get_workflow_chain(
        self,
        run_id: str,
    ) -> list[WorkflowRun]:
        """
        Get all runs in a continue-as-new chain.

        Given any run_id in a chain, returns all runs in the chain
        ordered from oldest to newest.

        Args:
            run_id: Any run ID in the chain

        Returns:
            List of WorkflowRun ordered from first to last in the chain
        """
        pass

    # Child Workflow Operations

    @abstractmethod
    async def get_children(
        self,
        parent_run_id: str,
        status: RunStatus | None = None,
    ) -> list[WorkflowRun]:
        """
        Get all child workflow runs for a parent workflow.

        Args:
            parent_run_id: Parent workflow run ID
            status: Optional filter by status

        Returns:
            List of child WorkflowRun instances
        """
        pass

    @abstractmethod
    async def get_parent(self, run_id: str) -> WorkflowRun | None:
        """
        Get the parent workflow run for a child workflow.

        Args:
            run_id: Child workflow run ID

        Returns:
            Parent WorkflowRun if exists, None if this is a root workflow
        """
        pass

    @abstractmethod
    async def get_nesting_depth(self, run_id: str) -> int:
        """
        Get the nesting depth for a workflow.

        Args:
            run_id: Workflow run ID

        Returns:
            Nesting depth (0=root, 1=child, 2=grandchild, max 3)
        """
        pass

    # Schedule Operations

    @abstractmethod
    async def create_schedule(self, schedule: Schedule) -> None:
        """
        Create a new schedule record.

        Args:
            schedule: Schedule instance to persist

        Raises:
            ValueError: If schedule_id already exists
        """
        pass

    @abstractmethod
    async def get_schedule(self, schedule_id: str) -> Schedule | None:
        """
        Retrieve a schedule by ID.

        Args:
            schedule_id: Schedule identifier

        Returns:
            Schedule if found, None otherwise
        """
        pass

    @abstractmethod
    async def update_schedule(self, schedule: Schedule) -> None:
        """
        Update an existing schedule.

        Replaces the schedule record with the provided schedule.
        The schedule_id must match an existing schedule.

        Args:
            schedule: Schedule with updated values

        Raises:
            ValueError: If schedule_id does not exist
        """
        pass

    @abstractmethod
    async def delete_schedule(self, schedule_id: str) -> None:
        """
        Mark a schedule as deleted (soft delete).

        Sets the schedule status to DELETED. The schedule record
        is preserved for audit purposes.

        Args:
            schedule_id: Schedule identifier

        Raises:
            ValueError: If schedule_id does not exist
        """
        pass

    @abstractmethod
    async def list_schedules(
        self,
        workflow_name: str | None = None,
        status: ScheduleStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Schedule]:
        """
        List schedules with optional filtering.

        Args:
            workflow_name: Filter by workflow name (None = all)
            status: Filter by status (None = all)
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of Schedule instances, sorted by created_at descending
        """
        pass

    @abstractmethod
    async def get_due_schedules(self, now: datetime) -> list[Schedule]:
        """
        Get all schedules that are due to run.

        Returns schedules where:
        - status is ACTIVE
        - next_run_time is not None
        - next_run_time <= now

        Args:
            now: Current datetime

        Returns:
            List of schedules due to run, sorted by next_run_time ascending
        """
        pass

    @abstractmethod
    async def add_running_run(self, schedule_id: str, run_id: str) -> None:
        """
        Add a run_id to the schedule's running_run_ids list.

        Called when a scheduled workflow starts execution.

        Args:
            schedule_id: Schedule identifier
            run_id: Run ID to add

        Raises:
            ValueError: If schedule_id does not exist
        """
        pass

    @abstractmethod
    async def remove_running_run(self, schedule_id: str, run_id: str) -> None:
        """
        Remove a run_id from the schedule's running_run_ids list.

        Called when a scheduled workflow completes (success or failure).

        Args:
            schedule_id: Schedule identifier
            run_id: Run ID to remove

        Raises:
            ValueError: If schedule_id does not exist
        """
        pass

    # Lifecycle

    async def connect(self) -> None:
        """
        Initialize connection to storage backend.

        Override if your backend requires explicit connection setup.
        """
        pass

    async def disconnect(self) -> None:
        """
        Close connection to storage backend.

        Override if your backend requires explicit cleanup.
        """
        pass

    async def health_check(self) -> bool:
        """
        Check if storage backend is healthy and accessible.

        Returns:
            True if healthy, False otherwise
        """
        try:
            # Simple check - try to list runs
            await self.list_runs(limit=1)  # Returns (runs, next_cursor)
            return True
        except Exception:
            return False
