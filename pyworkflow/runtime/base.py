"""
Abstract base class for workflow execution runtimes.

Runtimes are responsible for:
- Starting workflow executions
- Resuming suspended workflows
- Scheduling wake-up times for sleeps
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from pyworkflow.storage.base import StorageBackend


class Runtime(ABC):
    """
    Abstract base class for workflow execution runtimes.

    A runtime determines WHERE and HOW workflow code executes.
    Different runtimes support different capabilities (durable vs transient).
    """

    @abstractmethod
    async def start_workflow(
        self,
        workflow_func: Callable[..., Any],
        args: tuple,
        kwargs: dict,
        run_id: str,
        workflow_name: str,
        storage: Optional["StorageBackend"],
        durable: bool,
        idempotency_key: str | None = None,
        max_duration: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """
        Start a new workflow execution.

        Args:
            workflow_func: The workflow function to execute
            args: Positional arguments for the workflow
            kwargs: Keyword arguments for the workflow
            run_id: Unique identifier for this run
            workflow_name: Name of the workflow
            storage: Storage backend (None for transient workflows)
            durable: Whether this is a durable workflow
            idempotency_key: Optional key for idempotent execution
            max_duration: Optional maximum duration for the workflow
            metadata: Optional metadata dictionary

        Returns:
            The run_id of the started workflow
        """
        pass

    @abstractmethod
    async def resume_workflow(
        self,
        run_id: str,
        storage: "StorageBackend",
    ) -> Any:
        """
        Resume a suspended workflow.

        Args:
            run_id: The run_id of the workflow to resume
            storage: Storage backend containing workflow state

        Returns:
            The result of the workflow execution
        """
        pass

    @abstractmethod
    async def schedule_wake(
        self,
        run_id: str,
        wake_time: datetime,
        storage: "StorageBackend",
    ) -> None:
        """
        Schedule a workflow to be resumed at a specific time.

        Args:
            run_id: The run_id of the workflow to wake
            wake_time: When to resume the workflow
            storage: Storage backend
        """
        pass

    async def schedule_resume(
        self,
        run_id: str,
        storage: "StorageBackend",
    ) -> None:
        """
        Schedule a workflow to be resumed immediately.

        This is called by resume_hook() after recording the hook event.
        Each runtime implements this differently:
        - CeleryRuntime: Schedules an async Celery task
        - LocalRuntime: Calls resume_workflow directly (in-process)

        Args:
            run_id: The run_id of the workflow to resume
            storage: Storage backend
        """
        # Default implementation: no-op
        # Subclasses override if they support async scheduling
        pass

    @abstractmethod
    async def start_child_workflow(
        self,
        workflow_func: Callable[..., Any],
        args: tuple,
        kwargs: dict,
        child_run_id: str,
        workflow_name: str,
        storage: "StorageBackend",
        parent_run_id: str,
        child_id: str,
        wait_for_completion: bool,
    ) -> None:
        """
        Start a child workflow execution (fire-and-forget).

        Child workflows run in the background and notify the parent
        when completed/failed. If wait_for_completion=True, the parent
        will be resumed when the child finishes.

        Args:
            workflow_func: The child workflow function to execute
            args: Positional arguments for the child workflow
            kwargs: Keyword arguments for the child workflow
            child_run_id: Unique identifier for the child run
            workflow_name: Name of the child workflow
            storage: Storage backend
            parent_run_id: Run ID of the parent workflow
            child_id: Deterministic child ID for replay
            wait_for_completion: Whether parent is waiting for child to complete
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Runtime identifier.

        Returns:
            String identifier for this runtime (e.g., "local", "celery")
        """
        pass

    @property
    def supports_durable(self) -> bool:
        """
        Whether this runtime supports durable (event-sourced) workflows.

        Returns:
            True if durable workflows are supported
        """
        return True

    @property
    def supports_transient(self) -> bool:
        """
        Whether this runtime supports transient (non-durable) workflows.

        Returns:
            True if transient workflows are supported
        """
        return True
