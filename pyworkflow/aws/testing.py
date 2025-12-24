"""
Testing utilities for AWS Durable Lambda Functions.

This module provides mock implementations of AWS SDK components
for local testing without deploying to AWS.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from loguru import logger


class MockDuration:
    """Mock implementation of AWS Duration for testing."""

    def __init__(self, seconds: int) -> None:
        self._seconds = seconds

    @classmethod
    def from_seconds(cls, seconds: int) -> MockDuration:
        return cls(seconds)

    @classmethod
    def from_minutes(cls, minutes: int) -> MockDuration:
        return cls(minutes * 60)

    @classmethod
    def from_hours(cls, hours: int) -> MockDuration:
        return cls(hours * 3600)

    @property
    def seconds(self) -> int:
        return self._seconds


class MockDurableContext:
    """
    Mock implementation of AWS DurableContext for local testing.

    This class simulates the behavior of AWS Durable Execution SDK's
    DurableContext, allowing you to test workflows locally without
    deploying to AWS.

    The mock supports:
    - Step execution with optional checkpointing simulation
    - Wait/sleep (skipped in tests by default)
    - Checkpoint tracking for verification

    Usage:
        ```python
        from pyworkflow.aws.testing import MockDurableContext
        from pyworkflow.aws import AWSWorkflowContext

        def test_my_workflow():
            # Create mock context
            mock_ctx = MockDurableContext()
            aws_ctx = AWSWorkflowContext(mock_ctx)

            # Run workflow
            result = my_workflow(aws_ctx, order_id="123")

            # Verify checkpoints
            assert "validate_order" in mock_ctx.checkpoints
            assert mock_ctx.wait_count > 0
        ```
    """

    def __init__(
        self,
        skip_waits: bool = True,
        simulate_replay: bool = False,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the mock context.

        Args:
            skip_waits: If True, wait() calls return immediately (default: True)
            simulate_replay: If True, use checkpoint_data for replaying steps
            checkpoint_data: Pre-populated checkpoint data for replay simulation
        """
        self.skip_waits = skip_waits
        self.simulate_replay = simulate_replay

        # Tracking data
        self._checkpoints: dict[str, Any] = checkpoint_data or {}
        self._step_calls: list[dict[str, Any]] = []
        self._wait_calls: list[int] = []

    @property
    def checkpoints(self) -> dict[str, Any]:
        """Get all recorded checkpoints."""
        return self._checkpoints.copy()

    @property
    def step_calls(self) -> list[dict[str, Any]]:
        """Get list of all step() calls made."""
        return self._step_calls.copy()

    @property
    def wait_calls(self) -> list[int]:
        """Get list of all wait() durations (in seconds)."""
        return self._wait_calls.copy()

    @property
    def wait_count(self) -> int:
        """Get total number of wait() calls."""
        return len(self._wait_calls)

    def step(
        self,
        fn: Callable[[Any], Any],
        name: str | None = None,
    ) -> Any:
        """
        Execute a step function with checkpointing.

        In replay mode, returns cached result if available.
        Otherwise, executes the function and caches the result.

        Args:
            fn: The step function to execute
            name: Optional step name

        Returns:
            The result of the step function
        """
        step_name = name or f"step_{len(self._step_calls)}"

        logger.debug(f"Mock step: {step_name}")

        # Record the call
        call_info = {"name": step_name, "fn": fn}
        self._step_calls.append(call_info)

        # Check for replay
        if self.simulate_replay and step_name in self._checkpoints:
            logger.debug(f"Mock step replay: {step_name}")
            return self._checkpoints[step_name]

        # Execute the function
        result = fn(None)

        # Store checkpoint
        self._checkpoints[step_name] = result

        return result

    def wait(self, duration: MockDuration | int) -> None:
        """
        Wait for specified duration.

        Args:
            duration: MockDuration or seconds to wait
        """
        seconds = duration.seconds if isinstance(duration, MockDuration) else int(duration)

        logger.debug(f"Mock wait: {seconds} seconds")

        # Record the call
        self._wait_calls.append(seconds)

        # Optionally skip the actual wait
        if not self.skip_waits:
            import time

            time.sleep(seconds)

    def create_callback(
        self,
        name: str | None = None,
        config: Any | None = None,
    ) -> MockCallback:
        """
        Create a callback for external input (webhook/approval).

        Args:
            name: Optional callback name
            config: Optional callback configuration

        Returns:
            MockCallback object
        """
        callback_name = name or f"callback_{len(self._step_calls)}"
        logger.debug(f"Mock create_callback: {callback_name}")
        return MockCallback(callback_name)

    def wait_for_callback(
        self,
        fn: Callable[[str], Any],
        name: str | None = None,
        config: Any | None = None,
    ) -> Any:
        """
        Wait for a callback (combines create_callback + result).

        Args:
            fn: Function that takes callback_id and triggers external process
            name: Optional callback name
            config: Optional callback configuration

        Returns:
            The callback result
        """
        callback_name = name or f"callback_{len(self._step_calls)}"
        logger.debug(f"Mock wait_for_callback: {callback_name}")

        # Execute the function with a mock callback ID
        callback_id = f"mock_callback_{callback_name}"
        fn(callback_id)

        # Return mock result
        return {"callback_id": callback_id, "received": True}

    def parallel(self, *tasks: Callable[[MockDurableContext], Any]) -> list[Any]:
        """
        Execute multiple tasks in parallel.

        Args:
            *tasks: Task functions that take context as argument

        Returns:
            List of results from all tasks
        """
        logger.debug(f"Mock parallel: {len(tasks)} tasks")
        results = []
        for task in tasks:
            result = task(self)
            results.append(result)
        return results

    def reset(self) -> None:
        """Reset all tracking data for a fresh test run."""
        self._checkpoints.clear()
        self._step_calls.clear()
        self._wait_calls.clear()


class MockCallback:
    """Mock callback for testing webhook/approval patterns."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.callback_id = f"mock_callback_{name}"
        self._result: Any | None = None
        self._completed = False

    def complete(self, payload: Any) -> None:
        """Complete the callback with a payload."""
        self._result = payload
        self._completed = True

    def result(self) -> Any:
        """
        Get the callback result.

        In tests, you typically call complete() before result().
        """
        if not self._completed:
            # Return mock result for testing
            return {"callback_id": self.callback_id, "mock": True}
        return self._result


def create_test_handler(
    workflow_fn: Callable[..., Any],
    mock_ctx: MockDurableContext | None = None,
) -> Callable[[dict[str, Any]], Any]:
    """
    Create a test handler for a PyWorkflow workflow.

    This function creates a handler that can be used in tests without
    the AWS SDK dependency.

    Usage:
        ```python
        @workflow
        async def my_workflow(ctx, data: str):
            return {"result": data}

        handler = create_test_handler(my_workflow)
        result = handler({"data": "test"})
        assert result == {"result": "test"}
        ```

    Args:
        workflow_fn: A PyWorkflow workflow function
        mock_ctx: Optional MockDurableContext (creates one if not provided)

    Returns:
        A test handler function
    """
    from .context import AWSWorkflowContext

    def test_handler(event: dict[str, Any]) -> Any:
        ctx = mock_ctx or MockDurableContext()
        aws_ctx = AWSWorkflowContext(ctx)

        try:
            if asyncio.iscoroutinefunction(workflow_fn):
                return asyncio.run(workflow_fn(aws_ctx, **event))
            return workflow_fn(aws_ctx, **event)
        finally:
            aws_ctx.cleanup()

    return test_handler
