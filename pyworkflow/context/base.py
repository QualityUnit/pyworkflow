"""
WorkflowContext - Base class for all workflow execution contexts.

Uses Python's contextvars for implicit context passing, similar to Scala's implicits.
The context is automatically available within workflow execution without explicit passing.

Usage:
    from pyworkflow.context import get_context

    async def my_step(order_id: str):
        ctx = get_context()  # Implicitly available
        ctx.log(f"Processing {order_id}")
        return {"order_id": order_id}

    @workflow()
    async def my_workflow(order_id: str):
        # Context is set automatically by @workflow
        result = await my_step(order_id)
        await sleep("5m")  # sleep() uses implicit context
        return result
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, TypeVar

from loguru import logger

if TYPE_CHECKING:
    from pydantic import BaseModel

# Type for step functions
T = TypeVar("T")
StepFunction = Callable[..., T | Coroutine[Any, Any, T]]

# Global context variable - the implicit context
_current_context: ContextVar[WorkflowContext | None] = ContextVar("workflow_context", default=None)


def get_context() -> WorkflowContext:
    """
    Get the current workflow context (implicit).

    This function retrieves the context that was set when the workflow started.
    It should be called from within a workflow or step execution.

    Returns:
        The current WorkflowContext

    Raises:
        RuntimeError: If called outside of a workflow context

    Example:
        async def my_step(data: str):
            ctx = get_context()
            ctx.log(f"Processing: {data}")
            return {"data": data}
    """
    ctx = _current_context.get()
    if ctx is None:
        raise RuntimeError(
            "No workflow context available. "
            "This function must be called within a workflow execution. "
            "Make sure you're using the @workflow decorator."
        )
    return ctx


def has_context() -> bool:
    """
    Check if a workflow context is currently available.

    Returns:
        True if context is available, False otherwise
    """
    return _current_context.get() is not None


def set_context(ctx: WorkflowContext | None) -> Token:
    """
    Set the current workflow context.

    This is typically called by the workflow decorator, not user code.

    Args:
        ctx: The context to set, or None to clear

    Returns:
        Token that can be used to reset the context
    """
    return _current_context.set(ctx)


def reset_context(token: Token) -> None:
    """
    Reset the context to its previous value.

    Args:
        token: Token from set_context()
    """
    _current_context.reset(token)


class WorkflowContext(ABC):
    """
    Abstract base class for all workflow execution contexts.

    All context implementations (Local, AWS, Mock) must inherit from this class
    and implement the abstract methods.

    The context provides:
    - Step execution with checkpointing
    - Sleep/wait operations
    - Parallel execution
    - Logging with workflow context
    """

    def __init__(
        self,
        run_id: str = "unknown",
        workflow_name: str = "unknown",
    ) -> None:
        """
        Initialize base context.

        Args:
            run_id: Unique identifier for this workflow run
            workflow_name: Name of the workflow
        """
        self._run_id = run_id
        self._workflow_name = workflow_name

    @property
    def run_id(self) -> str:
        """Get the current workflow run ID."""
        return self._run_id

    @property
    def workflow_name(self) -> str:
        """Get the current workflow name."""
        return self._workflow_name

    # =========================================================================
    # Abstract methods - must be implemented by subclasses
    # =========================================================================

    @abstractmethod
    async def run(
        self,
        func: StepFunction[T],
        *args: Any,
        name: str | None = None,
        **kwargs: Any,
    ) -> T:
        """
        Execute a step function with context-appropriate handling.

        Args:
            func: The step function to execute (sync or async)
            *args: Positional arguments to pass to the function
            name: Optional step name for logging/checkpointing
            **kwargs: Keyword arguments to pass to the function

        Returns:
            The result of the step function
        """
        ...

    @abstractmethod
    async def sleep(self, duration: str | int | float) -> None:
        """
        Pause workflow execution for the specified duration.

        Args:
            duration: Sleep duration as:
                - str: Duration string ("5s", "10m", "1h", "1d")
                - int/float: Duration in seconds
        """
        ...

    @abstractmethod
    async def hook(
        self,
        name: str,
        timeout: int | None = None,
        on_created: Callable[[str], Awaitable[None]] | None = None,
        payload_schema: type[BaseModel] | None = None,
    ) -> Any:
        """
        Wait for an external event (webhook, approval, callback).

        The workflow suspends until resume_hook() is called with the token.
        Token is auto-generated in format "run_id:hook_id".

        Args:
            name: Human-readable name for the hook (for logging/debugging)
            timeout: Optional timeout in seconds. None means wait forever.
            on_created: Optional async callback called with token when hook is created.
            payload_schema: Optional Pydantic model for payload validation.

        Returns:
            The payload passed to resume_hook()

        Raises:
            HookExpiredError: If timeout is reached before resume
            NotImplementedError: If context doesn't support hooks (transient mode)
        """
        ...

    # =========================================================================
    # Cancellation support
    # =========================================================================

    @abstractmethod
    def is_cancellation_requested(self) -> bool:
        """
        Check if cancellation has been requested for this workflow.

        Returns:
            True if cancellation was requested, False otherwise
        """
        ...

    @abstractmethod
    def request_cancellation(self, reason: str | None = None) -> None:
        """
        Mark this workflow as cancelled.

        This sets the cancellation flag. The workflow will raise
        CancellationError at the next cancellation check point.

        Args:
            reason: Optional reason for cancellation
        """
        ...

    @abstractmethod
    def check_cancellation(self) -> None:
        """
        Check for cancellation and raise if requested.

        This should be called at interruptible points (before steps,
        during sleeps, etc.) to allow graceful cancellation.

        Raises:
            CancellationError: If cancellation was requested and not blocked
        """
        ...

    @property
    @abstractmethod
    def cancellation_blocked(self) -> bool:
        """
        Check if cancellation is currently blocked (within a shield scope).

        Returns:
            True if cancellation is blocked, False otherwise
        """
        ...

    # =========================================================================
    # Durable execution support - used by step decorator
    # =========================================================================

    @property
    def is_durable(self) -> bool:
        """Check if running in durable (event-sourced) mode."""
        return False  # Default: transient mode

    @property
    def is_replaying(self) -> bool:
        """Check if currently replaying events."""
        return False

    @property
    def storage(self) -> Any | None:
        """Get the storage backend."""
        return None

    @property
    def runtime(self) -> str | None:
        """
        Get the runtime environment slug.

        Returns the runtime identifier (e.g., "celery", "temporal") or None
        for local/inline execution. Used to determine step dispatch behavior.

        Returns:
            Runtime slug string or None for local execution
        """
        return None  # Default: local/inline execution

    @property
    def storage_config(self) -> dict[str, Any] | None:
        """Get storage configuration for distributed workers."""
        return None

    def has_step_failed(self, step_id: str) -> bool:
        """Check if a step has a recorded failure."""
        return False  # Default: no failures

    def get_step_failure(self, step_id: str) -> dict[str, Any] | None:
        """Get failure info for a step."""
        return None  # Default: no failure info

    def should_execute_step(self, step_id: str) -> bool:
        """Check if step should be executed (not already completed)."""
        return True  # Default: always execute

    def get_step_result(self, step_id: str) -> Any:
        """Get cached step result."""
        raise KeyError(f"Step {step_id} not found")

    def cache_step_result(self, step_id: str, result: Any) -> None:
        """Cache step result for replay."""
        pass  # Default: no caching

    def get_retry_state(self, step_id: str) -> dict[str, Any] | None:
        """Get retry state for a step."""
        return None

    def set_retry_state(
        self,
        step_id: str,
        attempt: int,
        resume_at: Any,
        max_retries: int,
        retry_delay: Any,
        last_error: str,
    ) -> None:
        """Set retry state for a step."""
        pass

    def clear_retry_state(self, step_id: str) -> None:
        """Clear retry state for a step."""
        pass

    async def validate_event_limits(self) -> None:
        """Validate event count against configured limits."""
        pass  # Default: no validation

    # =========================================================================
    # Child workflow support - used by start_child_workflow
    # =========================================================================

    @property
    def pending_children(self) -> dict[str, str]:
        """Get pending child workflows (child_id -> child_run_id)."""
        return {}

    def has_child_result(self, child_id: str) -> bool:
        """Check if a child workflow result exists."""
        return False

    def get_child_result(self, child_id: str) -> dict[str, Any]:
        """Get cached child workflow result."""
        return {}

    # =========================================================================
    # Optional methods - can be overridden by subclasses
    # =========================================================================

    async def parallel(self, *tasks: Coroutine[Any, Any, T]) -> list[T]:
        """
        Execute multiple tasks in parallel.

        Default implementation uses asyncio.gather.
        Subclasses may override for optimized parallel execution.

        Args:
            *tasks: Coroutines to execute in parallel

        Returns:
            List of results in the same order as input tasks
        """
        return list(await asyncio.gather(*tasks))

    async def wait_for_event(
        self,
        event_name: str,
        timeout: str | int | None = None,
    ) -> Any:
        """
        Wait for an external event (webhook, approval, callback).

        Default implementation raises NotImplementedError.
        Subclasses should override if they support external events.

        Args:
            event_name: Name/identifier for the event
            timeout: Optional timeout duration

        Returns:
            The event payload when received
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support wait_for_event. "
            "Use a context that supports external events (e.g., LocalContext with durable=True)."
        )

    # =========================================================================
    # Utility methods
    # =========================================================================

    def log(self, message: str, level: str = "info", **kwargs: Any) -> None:
        """
        Log a message with workflow context.

        Args:
            message: Log message
            level: Log level (debug, info, warning, error)
            **kwargs: Additional context to include in log
        """
        log_fn = getattr(logger, level, logger.info)
        log_fn(
            message,
            run_id=self._run_id,
            workflow_name=self._workflow_name,
            **kwargs,
        )

    def __enter__(self) -> WorkflowContext:
        """Context manager entry - set as current context."""
        self._token = set_context(self)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - restore previous context."""
        reset_context(self._token)

    async def __aenter__(self) -> WorkflowContext:
        """Async context manager entry."""
        self._token = set_context(self)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        reset_context(self._token)
