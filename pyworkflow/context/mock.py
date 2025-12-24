"""
MockContext - Testing context for workflows.

Provides a simple context implementation for testing workflows without
any side effects. Tracks all operations for verification.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from loguru import logger

from pyworkflow.context.base import StepFunction, WorkflowContext


class MockContext(WorkflowContext):
    """
    Mock context for testing workflows.

    Features:
    - Executes steps directly (no checkpointing)
    - Skips sleeps by default (configurable)
    - Tracks all operations for verification
    - Supports injecting mock results

    Example:
        def test_my_workflow():
            ctx = MockContext()

            result = asyncio.run(my_workflow(ctx, "test_input"))

            # Verify steps were called
            assert ctx.step_count == 3
            assert "validate_order" in ctx.step_names

            # Verify sleeps
            assert ctx.sleep_count == 1
            assert ctx.total_sleep_seconds == 300
    """

    def __init__(
        self,
        run_id: str = "test_run",
        workflow_name: str = "test_workflow",
        skip_sleeps: bool = True,
        mock_results: Optional[Dict[str, Any]] = None,
        mock_events: Optional[Dict[str, Any]] = None,
        mock_hooks: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize mock context.

        Args:
            run_id: Run ID for the test
            workflow_name: Workflow name for the test
            skip_sleeps: If True, sleeps return immediately
            mock_results: Dict of step_name -> result for mocking step results
            mock_events: Dict of event_name -> payload for mocking events
            mock_hooks: Dict of hook_name -> payload for mocking hook results
        """
        super().__init__(run_id=run_id, workflow_name=workflow_name)
        self._skip_sleeps = skip_sleeps
        self._mock_results = mock_results or {}
        self._mock_events = mock_events or {}
        self._mock_hooks = mock_hooks or {}

        # Tracking
        self._steps: List[Dict[str, Any]] = []
        self._sleeps: List[Dict[str, Any]] = []
        self._events: List[Dict[str, Any]] = []
        self._hooks: List[Dict[str, Any]] = []
        self._parallel_calls: List[int] = []

    # =========================================================================
    # Tracking properties
    # =========================================================================

    @property
    def steps(self) -> List[Dict[str, Any]]:
        """Get all step executions."""
        return self._steps.copy()

    @property
    def step_count(self) -> int:
        """Get number of steps executed."""
        return len(self._steps)

    @property
    def step_names(self) -> List[str]:
        """Get names of all executed steps."""
        return [s["name"] for s in self._steps]

    @property
    def sleeps(self) -> List[Dict[str, Any]]:
        """Get all sleep calls."""
        return self._sleeps.copy()

    @property
    def sleep_count(self) -> int:
        """Get number of sleep calls."""
        return len(self._sleeps)

    @property
    def total_sleep_seconds(self) -> int:
        """Get total seconds slept."""
        return sum(s["seconds"] for s in self._sleeps)

    @property
    def events(self) -> List[Dict[str, Any]]:
        """Get all event waits."""
        return self._events.copy()

    @property
    def hooks(self) -> List[Dict[str, Any]]:
        """Get all hook waits."""
        return self._hooks.copy()

    @property
    def hook_count(self) -> int:
        """Get number of hook calls."""
        return len(self._hooks)

    @property
    def hook_names(self) -> List[str]:
        """Get names of all hooks."""
        return [h["name"] for h in self._hooks]

    # =========================================================================
    # Step execution
    # =========================================================================

    async def run(
        self,
        func: StepFunction,
        *args: Any,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a step function.

        If a mock result is configured for this step, returns the mock.
        Otherwise executes the function directly.

        Args:
            func: Step function to execute
            *args: Arguments for the function
            name: Optional step name
            **kwargs: Keyword arguments

        Returns:
            Step result (real or mocked)
        """
        step_name = name or getattr(func, "__name__", "step")

        # Track the call
        self._steps.append({
            "name": step_name,
            "func": func,
            "args": args,
            "kwargs": kwargs,
        })

        logger.debug(f"[mock] Running step: {step_name}")

        # Check for mock result
        if step_name in self._mock_results:
            logger.debug(f"[mock] Using mock result for: {step_name}")
            return self._mock_results[step_name]

        # Execute the function
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    # =========================================================================
    # Sleep
    # =========================================================================

    async def sleep(self, duration: Union[str, int, float]) -> None:
        """
        Sleep for the specified duration.

        By default, returns immediately. Set skip_sleeps=False to actually sleep.

        Args:
            duration: Sleep duration
        """
        from pyworkflow.utils.duration import parse_duration

        if isinstance(duration, str):
            duration_seconds = parse_duration(duration)
        else:
            duration_seconds = int(duration)

        # Track the call
        self._sleeps.append({
            "duration": duration,
            "seconds": duration_seconds,
        })

        logger.debug(f"[mock] Sleep: {duration_seconds}s (skip={self._skip_sleeps})")

        if not self._skip_sleeps:
            await asyncio.sleep(duration_seconds)

    # =========================================================================
    # Parallel execution
    # =========================================================================

    async def parallel(self, *tasks) -> List[Any]:
        """Execute tasks in parallel (tracking the call)."""
        self._parallel_calls.append(len(tasks))
        return list(await asyncio.gather(*tasks))

    # =========================================================================
    # External events
    # =========================================================================

    async def wait_for_event(
        self,
        event_name: str,
        timeout: Optional[Union[str, int]] = None,
    ) -> Any:
        """
        Wait for an external event.

        Returns mock event data if configured, otherwise returns a default dict.

        Args:
            event_name: Event name
            timeout: Optional timeout

        Returns:
            Mock event payload
        """
        # Track the call
        self._events.append({
            "name": event_name,
            "timeout": timeout,
        })

        logger.debug(f"[mock] Waiting for event: {event_name}")

        # Check for mock event
        if event_name in self._mock_events:
            return self._mock_events[event_name]

        # Return default mock data
        return {"event": event_name, "mock": True}

    async def hook(
        self,
        name: str,
        timeout: Optional[int] = None,
        on_created: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Any:
        """
        Wait for an external event (hook).

        Returns mock hook payload if configured, otherwise returns a default dict.

        Args:
            name: Hook name
            timeout: Optional timeout in seconds (tracked but not enforced)
            on_created: Optional callback called with token (for testing)

        Returns:
            Mock hook payload
        """
        # Generate mock composite token: run_id:hook_name_counter
        self._hook_counter = getattr(self, "_hook_counter", 0) + 1
        hook_id = f"hook_{name}_{self._hook_counter}"
        actual_token = f"{self._run_id}:{hook_id}"

        # Track the call
        self._hooks.append({
            "name": name,
            "token": actual_token,
            "timeout": timeout,
        })

        logger.debug(f"[mock] Waiting for hook: {name} (token={actual_token[:20]}...)")

        # Call on_created callback if provided
        if on_created is not None:
            await on_created(actual_token)

        # Check for mock hook payload
        if name in self._mock_hooks:
            return self._mock_hooks[name]

        # Return default mock data
        return {"hook": name, "mock": True}

    # =========================================================================
    # Utility methods
    # =========================================================================

    def reset(self) -> None:
        """Reset all tracking data."""
        self._steps.clear()
        self._sleeps.clear()
        self._events.clear()
        self._hooks.clear()
        self._parallel_calls.clear()

    def assert_step_called(self, step_name: str, times: Optional[int] = None) -> None:
        """
        Assert a step was called.

        Args:
            step_name: Name of the step
            times: Optional expected call count
        """
        call_count = sum(1 for s in self._steps if s["name"] == step_name)

        if times is not None:
            assert call_count == times, (
                f"Step '{step_name}' expected {times} calls, got {call_count}"
            )
        else:
            assert call_count > 0, f"Step '{step_name}' was not called"

    def assert_slept(self, total_seconds: Optional[int] = None) -> None:
        """
        Assert sleep was called.

        Args:
            total_seconds: Optional expected total sleep time
        """
        assert self.sleep_count > 0, "No sleep calls recorded"

        if total_seconds is not None:
            assert self.total_sleep_seconds == total_seconds, (
                f"Expected {total_seconds}s total sleep, got {self.total_sleep_seconds}s"
            )
