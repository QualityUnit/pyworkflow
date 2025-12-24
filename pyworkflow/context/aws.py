"""
AWSContext - AWS Durable Lambda Functions execution context.

This context wraps the AWS Durable Execution SDK to provide PyWorkflow's
context interface while leveraging AWS native checkpointing and durability.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from pyworkflow.context.base import StepFunction, WorkflowContext
from pyworkflow.utils.duration import parse_duration

if TYPE_CHECKING:
    from aws_durable_execution_sdk_python import DurableContext


class AWSContext(WorkflowContext):
    """
    AWS Durable Lambda Functions execution context.

    This context wraps the AWS Durable Execution SDK's DurableContext,
    translating PyWorkflow operations to AWS SDK calls:

    - ctx.run() -> context.step()
    - ctx.sleep() -> context.wait()
    - ctx.wait_for_event() -> context.wait_for_callback()
    - ctx.parallel() -> context.parallel()

    AWS handles all checkpointing, replay, and durability automatically.

    Example:
        # Created by @aws_workflow decorator, not directly
        @aws_workflow()
        async def my_workflow(ctx: AWSContext, order_id: str):
            result = await ctx.run(validate_order, order_id)
            await ctx.sleep("5m")  # No compute charges!
            return result
    """

    def __init__(
        self,
        aws_context: DurableContext,
        run_id: str = "aws_run",
        workflow_name: str = "aws_workflow",
    ) -> None:
        """
        Initialize AWS context.

        Args:
            aws_context: The AWS DurableContext from Lambda handler
            run_id: Run ID (extracted from Lambda or generated)
            workflow_name: Workflow name
        """
        super().__init__(run_id=run_id, workflow_name=workflow_name)
        self._aws_ctx = aws_context
        self._step_counter = 0

    @property
    def aws_context(self) -> DurableContext:
        """Get the underlying AWS DurableContext."""
        return self._aws_ctx

    # =========================================================================
    # Step execution
    # =========================================================================

    async def run(
        self,
        func: StepFunction,
        *args: Any,
        name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a step with AWS checkpointing.

        Uses AWS context.step() which provides:
        - Automatic checkpointing before/after execution
        - Replay support (returns cached result if already completed)
        - Retry handling

        Args:
            func: Step function to execute
            *args: Arguments for the function
            name: Optional step name (used for checkpointing)
            **kwargs: Keyword arguments

        Returns:
            Step result
        """
        step_name = name or getattr(func, "__name__", None)
        if not step_name:
            self._step_counter += 1
            step_name = f"step_{self._step_counter}"

        logger.debug(f"[aws] Running step: {step_name}")

        def execute_step(_: Any) -> Any:
            """Inner function for AWS context.step()."""
            if asyncio.iscoroutinefunction(func):
                # Run async function in event loop
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop is not None:
                    # Already in async context - use thread
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, func(*args, **kwargs))
                        return future.result()
                else:
                    return asyncio.run(func(*args, **kwargs))
            else:
                return func(*args, **kwargs)

        # Use AWS context.step() for checkpointing
        result = self._aws_ctx.step(execute_step, name=step_name)

        logger.debug(f"[aws] Step completed: {step_name}")
        return result

    # =========================================================================
    # Sleep
    # =========================================================================

    async def sleep(self, duration: str | int | float) -> None:
        """
        Sleep using AWS native wait (no compute charges).

        Uses AWS context.wait() which:
        - Suspends Lambda execution
        - No charges during wait time
        - Automatically resumes when duration elapses

        Args:
            duration: Sleep duration
        """
        duration_seconds = parse_duration(duration) if isinstance(duration, str) else int(duration)

        logger.debug(f"[aws] Sleeping: {duration_seconds}s")

        # Try to use AWS Duration, fall back to raw seconds for mock
        try:
            from aws_durable_execution_sdk_python.config import Duration

            duration_obj = Duration.from_seconds(duration_seconds)
        except ImportError:
            # Using mock context
            duration_obj = duration_seconds

        self._aws_ctx.wait(duration_obj)

        logger.debug(f"[aws] Sleep completed: {duration_seconds}s")

    # =========================================================================
    # Parallel execution
    # =========================================================================

    async def parallel(self, *tasks: Any) -> list[Any]:
        """
        Execute tasks in parallel using AWS context.parallel().

        Note: AWS parallel() has a different signature - it takes functions
        that receive a child context. For simplicity, we fall back to
        asyncio.gather for the MVP.

        Args:
            *tasks: Coroutines to execute in parallel

        Returns:
            List of results
        """
        # For MVP, use asyncio.gather
        # TODO: Use AWS context.parallel() for better checkpointing
        return list(await asyncio.gather(*tasks))

    # =========================================================================
    # External events (callbacks)
    # =========================================================================

    async def wait_for_event(
        self,
        event_name: str,
        timeout: str | int | None = None,
    ) -> Any:
        """
        Wait for an external event using AWS callbacks.

        Uses AWS context.create_callback() or context.wait_for_callback().

        Args:
            event_name: Name for the callback
            timeout: Optional timeout

        Returns:
            Callback payload when received
        """
        logger.debug(f"[aws] Waiting for event: {event_name}")

        # Parse timeout
        timeout_seconds = None
        if timeout:
            timeout_seconds = parse_duration(timeout) if isinstance(timeout, str) else int(timeout)

        try:
            from aws_durable_execution_sdk_python.config import CallbackConfig

            config = None
            if timeout_seconds:
                config = CallbackConfig(timeout_seconds=timeout_seconds)

            callback = self._aws_ctx.create_callback(name=event_name, config=config)

            # Return the callback result when available
            result = callback.result()

            logger.debug(f"[aws] Event received: {event_name}")
            return result

        except ImportError:
            # Mock context - return mock data
            return {"event": event_name, "mock": True}
