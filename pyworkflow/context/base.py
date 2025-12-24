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
from contextvars import ContextVar, Token
from typing import Any, Awaitable, Callable, Coroutine, List, Optional, TypeVar, Union

from loguru import logger

# Type for step functions
T = TypeVar("T")
StepFunction = Callable[..., Union[T, Coroutine[Any, Any, T]]]

# Global context variable - the implicit context
_current_context: ContextVar[Optional["WorkflowContext"]] = ContextVar(
    "workflow_context", default=None
)


def get_context() -> "WorkflowContext":
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


def set_context(ctx: Optional["WorkflowContext"]) -> Token:
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
        name: Optional[str] = None,
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
    async def sleep(self, duration: Union[str, int, float]) -> None:
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
        timeout: Optional[int] = None,
        on_created: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Any:
        """
        Wait for an external event (webhook, approval, callback).

        The workflow suspends until resume_hook() is called with the token.
        Token is auto-generated in format "run_id:hook_id".

        Args:
            name: Human-readable name for the hook (for logging/debugging)
            timeout: Optional timeout in seconds. None means wait forever.
            on_created: Optional async callback called with token when hook is created.

        Returns:
            The payload passed to resume_hook()

        Raises:
            HookExpiredError: If timeout is reached before resume
            NotImplementedError: If context doesn't support hooks (transient mode)
        """
        ...

    # =========================================================================
    # Optional methods - can be overridden by subclasses
    # =========================================================================

    async def parallel(self, *tasks: Coroutine[Any, Any, T]) -> List[T]:
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
        timeout: Optional[Union[str, int]] = None,
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

    def __enter__(self) -> "WorkflowContext":
        """Context manager entry - set as current context."""
        self._token = set_context(self)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - restore previous context."""
        reset_context(self._token)

    async def __aenter__(self) -> "WorkflowContext":
        """Async context manager entry."""
        self._token = set_context(self)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        reset_context(self._token)
