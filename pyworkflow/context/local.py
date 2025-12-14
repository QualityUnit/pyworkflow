"""
LocalContext - In-process workflow execution with optional event sourcing.

This context runs workflows locally with support for:
- Durable mode: Event sourcing, checkpointing, suspend/resume
- Transient mode: Simple execution without persistence
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any, Callable, Dict, List, Optional, Set, Union

from loguru import logger

from pyworkflow.context.base import StepFunction, WorkflowContext
from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.utils.duration import parse_duration


class LocalContext(WorkflowContext):
    """
    Local execution context with optional event sourcing.

    In durable mode:
    - Steps are checkpointed to storage
    - Sleeps suspend the workflow (can be resumed later)
    - Hooks wait for external events

    In transient mode:
    - Steps execute directly
    - Sleeps use asyncio.sleep
    - No persistence

    Example:
        # Create durable context
        ctx = LocalContext(
            run_id="run_123",
            workflow_name="order_workflow",
            storage=FileStorageBackend("./data"),
            durable=True,
        )

        # Or transient context
        ctx = LocalContext(
            run_id="run_456",
            workflow_name="quick_task",
            durable=False,
        )
    """

    def __init__(
        self,
        run_id: str = "local_run",
        workflow_name: str = "local_workflow",
        storage: Optional[Any] = None,
        durable: bool = True,
        event_log: Optional[List[Any]] = None,
    ) -> None:
        """
        Initialize local context.

        Args:
            run_id: Unique identifier for this workflow run
            workflow_name: Name of the workflow
            storage: Storage backend for event sourcing (required for durable)
            durable: Whether to use durable execution mode
            event_log: Existing events for replay (when resuming)
        """
        super().__init__(run_id=run_id, workflow_name=workflow_name)
        self._storage = storage
        self._durable = durable and storage is not None
        self._event_log = event_log or []

        # Execution state
        self._step_results: Dict[str, Any] = {}
        self._completed_sleeps: Set[str] = set()
        self._hook_results: Dict[str, Any] = {}
        self._step_counter = 0

        # Replay state if resuming
        if event_log:
            self._replay_events(event_log)

    def _replay_events(self, events: List[Any]) -> None:
        """Replay events to restore state."""
        from pyworkflow.engine.events import EventType
        from pyworkflow.serialization.decoder import deserialize

        for event in events:
            if event.type == EventType.STEP_COMPLETED:
                step_id = event.data.get("step_id")
                result = deserialize(event.data.get("result"))
                self._step_results[step_id] = result

            elif event.type == EventType.SLEEP_COMPLETED:
                sleep_id = event.data.get("sleep_id")
                self._completed_sleeps.add(sleep_id)

            elif event.type == EventType.HOOK_RECEIVED:
                hook_id = event.data.get("hook_id")
                payload = deserialize(event.data.get("payload"))
                self._hook_results[hook_id] = payload

    @property
    def is_durable(self) -> bool:
        return self._durable

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

        In durable mode:
        - Generates deterministic step ID
        - Checks for cached result (replay)
        - Records events to storage

        In transient mode:
        - Executes function directly

        Args:
            func: Step function to execute
            *args: Arguments for the function
            name: Optional step name
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the step function
        """
        step_name = name or getattr(func, "__name__", "step")

        if not self._durable:
            # Transient mode - execute directly
            logger.debug(f"[transient] Running step: {step_name}")
            return await self._execute_func(func, *args, **kwargs)

        # Durable mode - use event sourcing
        step_id = self._generate_step_id(step_name, args, kwargs)

        # Check if already completed (replay)
        if step_id in self._step_results:
            logger.debug(f"[replay] Step {step_name} already completed, using cached result")
            return self._step_results[step_id]

        # Record step start
        await self._record_step_start(step_id, step_name, args, kwargs)

        logger.info(f"Running step: {step_name}", run_id=self._run_id, step_id=step_id)

        try:
            # Execute the function
            result = await self._execute_func(func, *args, **kwargs)

            # Record completion
            await self._record_step_complete(step_id, result)

            # Cache result
            self._step_results[step_id] = result

            logger.info(f"Step completed: {step_name}", run_id=self._run_id, step_id=step_id)
            return result

        except Exception as e:
            await self._record_step_failed(step_id, e)
            raise

    async def _execute_func(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute a function, handling both sync and async."""
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    def _generate_step_id(self, step_name: str, args: tuple, kwargs: dict) -> str:
        """Generate deterministic step ID."""
        from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs

        args_str = serialize_args(*args)
        kwargs_str = serialize_kwargs(**kwargs)
        content = f"{step_name}:{args_str}:{kwargs_str}"
        hash_hex = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"step_{step_name}_{hash_hex}"

    async def _record_step_start(
        self, step_id: str, step_name: str, args: tuple, kwargs: dict
    ) -> None:
        """Record step started event."""
        from pyworkflow.engine.events import create_step_started_event
        from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs

        event = create_step_started_event(
            run_id=self._run_id,
            step_id=step_id,
            step_name=step_name,
            args=serialize_args(*args),
            kwargs=serialize_kwargs(**kwargs),
            attempt=1,
        )
        await self._storage.record_event(event)

    async def _record_step_complete(self, step_id: str, result: Any) -> None:
        """Record step completed event."""
        from pyworkflow.engine.events import create_step_completed_event
        from pyworkflow.serialization.encoder import serialize

        event = create_step_completed_event(
            run_id=self._run_id,
            step_id=step_id,
            result=serialize(result),
        )
        await self._storage.record_event(event)

    async def _record_step_failed(self, step_id: str, error: Exception) -> None:
        """Record step failed event."""
        from pyworkflow.engine.events import create_step_failed_event

        event = create_step_failed_event(
            run_id=self._run_id,
            step_id=step_id,
            error=str(error),
            error_type=type(error).__name__,
            is_retryable=True,
            attempt=1,
        )
        await self._storage.record_event(event)

    # =========================================================================
    # Sleep
    # =========================================================================

    async def sleep(self, duration: Union[str, int, float]) -> None:
        """
        Sleep for the specified duration.

        In durable mode:
        - Records sleep event
        - Raises SuspensionSignal to pause workflow
        - Workflow can be resumed later

        In transient mode:
        - Uses asyncio.sleep

        Args:
            duration: Sleep duration (string like "5m" or seconds)
        """
        # Parse duration
        if isinstance(duration, str):
            duration_seconds = parse_duration(duration)
        else:
            duration_seconds = int(duration)

        if not self._durable:
            # Transient mode - just sleep
            logger.debug(f"[transient] Sleeping {duration_seconds}s")
            await asyncio.sleep(duration_seconds)
            return

        # Durable mode - suspend workflow
        sleep_id = self._generate_sleep_id(duration_seconds)

        # Check if already completed (replay)
        if sleep_id in self._completed_sleeps:
            logger.debug(f"[replay] Sleep {sleep_id} already completed, skipping")
            return

        # Calculate resume time
        resume_at = datetime.now(UTC).timestamp() + duration_seconds

        # Check if we should resume now
        if datetime.now(UTC).timestamp() >= resume_at:
            logger.debug(f"Sleep {sleep_id} time elapsed, continuing")
            self._completed_sleeps.add(sleep_id)
            return

        # Record sleep started and suspend
        await self._record_sleep_start(sleep_id, duration_seconds, resume_at)

        logger.info(
            f"Suspending workflow for {duration_seconds}s",
            run_id=self._run_id,
            sleep_id=sleep_id,
        )

        raise SuspensionSignal(
            reason=f"sleep:{sleep_id}",
            resume_at=datetime.fromtimestamp(resume_at, tz=UTC),
        )

    def _generate_sleep_id(self, duration_seconds: int) -> str:
        """Generate deterministic sleep ID."""
        self._step_counter += 1
        return f"sleep_{self._step_counter}_{duration_seconds}s"

    async def _record_sleep_start(
        self, sleep_id: str, duration_seconds: int, resume_at: float
    ) -> None:
        """Record sleep started event."""
        from pyworkflow.engine.events import create_sleep_started_event

        event = create_sleep_started_event(
            run_id=self._run_id,
            sleep_id=sleep_id,
            duration_seconds=duration_seconds,
            resume_at=datetime.fromtimestamp(resume_at, tz=UTC),
        )
        await self._storage.record_event(event)

    # =========================================================================
    # Parallel execution
    # =========================================================================

    async def parallel(self, *tasks) -> List[Any]:
        """Execute multiple tasks in parallel."""
        return list(await asyncio.gather(*tasks))

    # =========================================================================
    # External events (hooks)
    # =========================================================================

    async def wait_for_event(
        self,
        event_name: str,
        timeout: Optional[Union[str, int]] = None,
    ) -> Any:
        """
        Wait for an external event.

        In durable mode:
        - Creates a hook
        - Suspends workflow waiting for webhook
        - Returns payload when webhook received

        Args:
            event_name: Name for the event/hook
            timeout: Optional timeout

        Returns:
            Event payload
        """
        if not self._durable:
            raise NotImplementedError(
                "wait_for_event requires durable mode with storage"
            )

        hook_id = f"hook_{event_name}_{self._step_counter}"
        self._step_counter += 1

        # Check if already received (replay)
        if hook_id in self._hook_results:
            logger.debug(f"[replay] Hook {hook_id} already received")
            return self._hook_results[hook_id]

        # Record hook created and suspend
        await self._record_hook_created(hook_id, event_name, timeout)

        logger.info(
            f"Waiting for event: {event_name}",
            run_id=self._run_id,
            hook_id=hook_id,
        )

        raise SuspensionSignal(
            reason=f"hook:{hook_id}",
            hook_id=hook_id,
        )

    async def _record_hook_created(
        self, hook_id: str, event_name: str, timeout: Optional[Union[str, int]]
    ) -> None:
        """Record hook created event."""
        from pyworkflow.engine.events import create_hook_created_event

        timeout_seconds = None
        if timeout:
            timeout_seconds = parse_duration(timeout) if isinstance(timeout, str) else int(timeout)

        event = create_hook_created_event(
            run_id=self._run_id,
            hook_id=hook_id,
            hook_name=event_name,
            timeout_seconds=timeout_seconds,
        )
        await self._storage.record_event(event)
