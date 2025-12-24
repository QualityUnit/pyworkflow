"""
AWS Durable Lambda Functions context adapter.

This module provides an adapter that wraps AWS DurableContext to work
with PyWorkflow's step and sleep primitives.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from loguru import logger

from pyworkflow.context.base import StepFunction, WorkflowContext
from pyworkflow.utils.duration import parse_duration

if TYPE_CHECKING:
    # Only import AWS SDK types for type checking
    # Actual import happens at runtime if available
    from aws_durable_execution_sdk_python import DurableContext


# Context variable to track current AWS context (for backward compatibility)
_aws_context: ContextVar[AWSWorkflowContext | None] = ContextVar(
    "aws_workflow_context", default=None
)


def get_aws_context() -> AWSWorkflowContext | None:
    """Get the current AWS workflow context if running in AWS environment."""
    return _aws_context.get()


def has_aws_context() -> bool:
    """Check if currently running in AWS Durable Lambda context."""
    return _aws_context.get() is not None


class AWSWorkflowContext(WorkflowContext):
    """
    Adapts AWS DurableContext to PyWorkflow's context interface.

    This class wraps the AWS Durable Execution SDK's context to provide
    a familiar interface for PyWorkflow primitives while leveraging
    AWS's native checkpointing and durability features.

    Attributes:
        _aws_ctx: The underlying AWS DurableContext
        _step_counter: Counter for generating unique step names
    """

    def __init__(
        self,
        aws_ctx: DurableContext,
        run_id: str = "aws_run",
        workflow_name: str = "aws_workflow",
    ) -> None:
        """
        Initialize the AWS workflow context adapter.

        Args:
            aws_ctx: The AWS DurableContext from the Lambda handler
            run_id: Optional run ID for logging
            workflow_name: Optional workflow name for logging
        """
        super().__init__(run_id=run_id, workflow_name=workflow_name)
        self._aws_ctx = aws_ctx
        self._step_counter = 0

        # Set this context as the current AWS context (for backward compatibility)
        _aws_context.set(self)

        logger.debug("AWS workflow context initialized")

    async def run(
        self,
        func: StepFunction,
        *args: Any,
        name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a step function with AWS checkpointing.

        This is the new unified interface for step execution.
        Uses AWS's context.step() for automatic checkpointing and replay.

        Args:
            func: Step function to execute
            *args: Arguments for the function
            name: Optional step name (used for checkpointing)
            **kwargs: Keyword arguments

        Returns:
            Step result
        """
        return self.execute_step(func, *args, step_name=name, **kwargs)

    def execute_step(
        self,
        step_fn: Callable[..., Any],
        *args: Any,
        step_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a step with AWS checkpointing (legacy interface).

        This method wraps a step function call with AWS's context.step(),
        which provides automatic checkpointing and replay behavior.

        Args:
            step_fn: The step function to execute
            *args: Positional arguments to pass to the step
            step_name: Optional name for the step (defaults to function name)
            **kwargs: Keyword arguments to pass to the step

        Returns:
            The result of the step function
        """
        # Generate step name
        name = step_name or getattr(step_fn, "__name__", None)
        if not name:
            self._step_counter += 1
            name = f"step_{self._step_counter}"

        logger.debug(f"Executing AWS step: {name}")

        def run_step(_: Any) -> Any:
            """Inner function to execute the step, handling async/sync."""
            # Check if the step function is async
            if asyncio.iscoroutinefunction(step_fn):
                # Get or create event loop for async execution
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop is not None:
                    # We're in an async context - create a task
                    # This shouldn't happen in normal AWS Lambda flow
                    # but handle it gracefully
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, step_fn(*args, **kwargs))
                        return future.result()
                else:
                    # No running loop - use asyncio.run()
                    return asyncio.run(step_fn(*args, **kwargs))
            else:
                # Synchronous function - execute directly
                return step_fn(*args, **kwargs)

        # Use AWS context.step() for checkpointing
        result = self._aws_ctx.step(run_step, name=name)

        logger.debug(f"AWS step completed: {name}")
        return result

    async def sleep(self, duration: str | int | float) -> None:
        """
        Sleep using AWS wait (no compute charges during wait).

        This method uses AWS's context.wait() which suspends the Lambda
        execution without incurring compute charges.

        Args:
            duration: Sleep duration as:
                - str: Duration string like "5s", "10m", "1h"
                - int/float: Duration in seconds
        """
        # Parse duration to seconds
        duration_seconds = parse_duration(duration) if isinstance(duration, str) else int(duration)

        logger.debug(f"AWS sleep: {duration_seconds} seconds")

        # Try to use AWS Duration, fall back to raw seconds for mock context
        try:
            from aws_durable_execution_sdk_python.config import Duration

            duration_obj = Duration.from_seconds(duration_seconds)
        except ImportError:
            # AWS SDK not installed - likely using mock context for testing
            # MockDurableContext.wait() accepts raw seconds
            duration_obj = duration_seconds

        # Use AWS context.wait() for cost-free waiting
        self._aws_ctx.wait(duration_obj)

        logger.debug(f"AWS sleep completed: {duration_seconds} seconds")

    async def parallel(self, *tasks: Any) -> list[Any]:
        """Execute tasks in parallel using asyncio.gather."""
        return list(await asyncio.gather(*tasks))

    # =========================================================================
    # Cancellation support (not fully implemented for AWS - defer to AWS SDK)
    # =========================================================================

    def is_cancellation_requested(self) -> bool:
        """Check if cancellation requested (AWS manages this internally)."""
        return False

    def request_cancellation(self, reason: str | None = None) -> None:
        """Request cancellation (AWS manages this internally)."""
        logger.warning("Cancellation not supported in AWS context")

    def check_cancellation(self) -> None:
        """Check cancellation (AWS manages this internally)."""
        pass  # AWS handles this

    @property
    def cancellation_blocked(self) -> bool:
        """Check if cancellation blocked."""
        return False

    async def hook(
        self,
        name: str,
        timeout: int | None = None,
        on_created: Callable[[str], Awaitable[None]] | None = None,
        payload_schema: type | None = None,
    ) -> Any:
        """Wait for hook (not implemented for AWS - use wait_for_callback)."""
        raise NotImplementedError("Use AWS context.wait_for_callback() instead")

    def cleanup(self) -> None:
        """Clean up the context when workflow completes."""
        _aws_context.set(None)
        logger.debug("AWS workflow context cleaned up")
