"""
Abstract base class for storage backends.

All storage implementations must implement this interface to ensure consistency
across different backends (File, Redis, SQLite, PostgreSQL).
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from pyworkflow.engine.events import Event
from pyworkflow.storage.schemas import Hook, RunStatus, StepExecution, WorkflowRun


class StorageBackend(ABC):
    """
    Abstract base class for workflow storage backends.

    Storage backends are responsible for:
    - Persisting workflow runs, steps, hooks
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
    async def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        """
        Retrieve a workflow run by ID.

        Args:
            run_id: Unique workflow run identifier

        Returns:
            WorkflowRun if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_run_by_idempotency_key(self, key: str) -> Optional[WorkflowRun]:
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
        result: Optional[str] = None,
        error: Optional[str] = None,
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
    async def list_runs(
        self,
        workflow_name: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[WorkflowRun]:
        """
        List workflow runs with optional filtering.

        Args:
            workflow_name: Filter by workflow name
            status: Filter by status
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of WorkflowRun instances
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
        event_types: Optional[List[str]] = None,
    ) -> List[Event]:
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
        event_type: Optional[str] = None,
    ) -> Optional[Event]:
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
    async def get_step(self, step_id: str) -> Optional[StepExecution]:
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
        result: Optional[str] = None,
        error: Optional[str] = None,
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
    async def list_steps(self, run_id: str) -> List[StepExecution]:
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
        Create a hook/webhook record.

        Args:
            hook: Hook instance to persist
        """
        pass

    @abstractmethod
    async def get_hook(self, hook_id: str) -> Optional[Hook]:
        """
        Retrieve a hook by ID.

        Args:
            hook_id: Hook identifier

        Returns:
            Hook if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_hook_by_token(self, run_id: str, token: str) -> Optional[Hook]:
        """
        Retrieve a hook by run_id and token (for webhook authentication).

        Args:
            run_id: Workflow run identifier
            token: Hook security token

        Returns:
            Hook if found and token matches, None otherwise
        """
        pass

    @abstractmethod
    async def update_hook_payload(
        self,
        hook_id: str,
        payload: str,
        status: Optional[str] = None,
    ) -> None:
        """
        Update hook with received payload.

        Args:
            hook_id: Hook identifier
            payload: Serialized payload from webhook
            status: Optional new status
        """
        pass

    @abstractmethod
    async def list_hooks(self, run_id: str) -> List[Hook]:
        """
        List all hooks for a workflow run.

        Args:
            run_id: Workflow run identifier

        Returns:
            List of Hook instances
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
            await self.list_runs(limit=1)
            return True
        except Exception:
            return False
