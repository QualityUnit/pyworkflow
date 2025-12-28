"""
LocalContext - In-process workflow execution with optional event sourcing.

This context runs workflows locally with support for:
- Durable mode: Event sourcing, checkpointing, suspend/resume
- Transient mode: Simple execution without persistence
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel

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
        storage: Any | None = None,
        durable: bool = True,
        event_log: list[Any] | None = None,
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
        self._step_results: dict[str, Any] = {}
        self._completed_sleeps: set[str] = set()
        self._pending_sleeps: dict[str, Any] = {}
        self._hook_results: dict[str, Any] = {}
        self._pending_hooks: dict[str, Any] = {}
        self._step_counter = 0
        self._retry_states: dict[str, dict[str, Any]] = {}
        self._is_replaying = False
        self._last_warning_count: int = 0  # Track last event count for warning interval

        # Cancellation state
        self._cancellation_requested: bool = False
        self._cancellation_blocked: bool = False
        self._cancellation_reason: str | None = None

        # Child workflow state
        self._child_results: dict[str, dict[str, Any]] = {}
        self._pending_children: dict[str, str] = {}  # child_id -> child_run_id

        # Runtime environment (e.g., "celery", "temporal", None for local)
        self._runtime: str | None = None
        self._storage_config: dict[str, Any] | None = None

        # Step failure tracking (for handling failures during replay)
        self._step_failures: dict[str, dict[str, Any]] = {}

        # Replay state if resuming
        if event_log:
            self._is_replaying = True
            self._replay_events(event_log)
            self._is_replaying = False

    def _replay_events(self, events: list[Any]) -> None:
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

            elif event.type == EventType.STEP_RETRYING:
                step_id = event.data.get("step_id")
                self._retry_states[step_id] = {
                    "step_id": step_id,
                    "current_attempt": event.data.get("attempt", 1),
                    "resume_at": event.data.get("resume_at"),
                    "max_retries": event.data.get("max_retries", 3),
                    "retry_delay": event.data.get("retry_strategy", "exponential"),
                    "last_error": event.data.get("error", ""),
                }

            elif event.type == EventType.STEP_FAILED:
                # Track step failures for distributed step dispatch
                # If a step failed (not retrying), record it for replay detection
                step_id = event.data.get("step_id")
                is_retryable = event.data.get("is_retryable", True)
                # Only track as a final failure if not retryable or if this is
                # the last failure before a STEP_COMPLETED event
                # For now, track all failures - the step decorator will check
                # if there's also a STEP_COMPLETED event
                if step_id and not is_retryable:
                    self._step_failures[step_id] = {
                        "error": event.data.get("error", "Unknown error"),
                        "error_type": event.data.get("error_type", "Exception"),
                        "is_retryable": is_retryable,
                    }

            elif event.type == EventType.CANCELLATION_REQUESTED:
                self._cancellation_requested = True
                self._cancellation_reason = event.data.get("reason")

            # Child workflow events
            elif event.type == EventType.CHILD_WORKFLOW_STARTED:
                child_id = event.data.get("child_id")
                child_run_id = event.data.get("child_run_id")
                if child_id and child_run_id:
                    self._pending_children[child_id] = child_run_id

            elif event.type == EventType.CHILD_WORKFLOW_COMPLETED:
                child_id = event.data.get("child_id")
                child_run_id = event.data.get("child_run_id")
                result = deserialize(event.data.get("result"))
                if child_id:
                    self._child_results[child_id] = {
                        "child_run_id": child_run_id,
                        "result": result,
                        "__failed__": False,
                    }
                    self._pending_children.pop(child_id, None)

            elif event.type == EventType.CHILD_WORKFLOW_FAILED:
                child_id = event.data.get("child_id")
                child_run_id = event.data.get("child_run_id")
                error = event.data.get("error")
                error_type = event.data.get("error_type")
                if child_id:
                    self._child_results[child_id] = {
                        "child_run_id": child_run_id,
                        "error": error,
                        "error_type": error_type,
                        "__failed__": True,
                    }
                    self._pending_children.pop(child_id, None)

            elif event.type == EventType.CHILD_WORKFLOW_CANCELLED:
                child_id = event.data.get("child_id")
                child_run_id = event.data.get("child_run_id")
                reason = event.data.get("reason")
                if child_id:
                    self._child_results[child_id] = {
                        "child_run_id": child_run_id,
                        "error": f"Cancelled: {reason}",
                        "error_type": "CancellationError",
                        "__failed__": True,
                    }
                    self._pending_children.pop(child_id, None)

    @property
    def is_durable(self) -> bool:
        return self._durable

    @property
    def storage(self) -> Any | None:
        """Get the storage backend."""
        return self._storage

    def _get_storage(self) -> Any:
        """Get storage backend, asserting it's not None (for durable mode)."""
        assert self._storage is not None, "Storage not available in transient mode"
        return self._storage

    @property
    def is_replaying(self) -> bool:
        """Check if currently replaying events."""
        return self._is_replaying

    @is_replaying.setter
    def is_replaying(self, value: bool) -> None:
        """Set replay mode."""
        self._is_replaying = value

    @property
    def runtime(self) -> str | None:
        """
        Get the runtime environment slug.

        Returns the runtime identifier (e.g., "celery", "temporal") or None
        for local/inline execution. Used to determine step dispatch behavior.

        Returns:
            Runtime slug string or None for local execution
        """
        return self._runtime

    @property
    def storage_config(self) -> dict[str, Any] | None:
        """
        Get storage configuration for distributed workers.

        This is passed to step workers so they can connect to the same storage.
        """
        return self._storage_config

    # =========================================================================
    # Step result caching (for @step decorator compatibility)
    # =========================================================================

    def should_execute_step(self, step_id: str) -> bool:
        """Check if a step should be executed (not already cached)."""
        return step_id not in self._step_results

    def get_step_result(self, step_id: str) -> Any:
        """Get cached step result."""
        return self._step_results.get(step_id)

    def cache_step_result(self, step_id: str, result: Any) -> None:
        """Cache a step result."""
        self._step_results[step_id] = result

    # =========================================================================
    # Retry state management (for @step decorator compatibility)
    # =========================================================================

    def get_retry_state(self, step_id: str) -> dict[str, Any] | None:
        """Get retry state for a step."""
        return self._retry_states.get(step_id)

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
        self._retry_states[step_id] = {
            "step_id": step_id,
            "current_attempt": attempt,
            "resume_at": resume_at,
            "max_retries": max_retries,
            "retry_delay": retry_delay,
            "last_error": last_error,
        }

    def clear_retry_state(self, step_id: str) -> None:
        """Clear retry state for a step."""
        self._retry_states.pop(step_id, None)

    # =========================================================================
    # Step failure tracking (for distributed step dispatch)
    # =========================================================================

    def has_step_failed(self, step_id: str) -> bool:
        """
        Check if a step has a recorded failure.

        Used during replay to detect steps that failed on a remote worker.
        """
        return step_id in self._step_failures

    def get_step_failure(self, step_id: str) -> dict[str, Any] | None:
        """
        Get step failure info.

        Returns:
            Dict with 'error', 'error_type', 'is_retryable' or None
        """
        return self._step_failures.get(step_id)

    def record_step_failure(
        self,
        step_id: str,
        error: str,
        error_type: str,
        is_retryable: bool,
    ) -> None:
        """Record a step failure for replay detection."""
        self._step_failures[step_id] = {
            "error": error,
            "error_type": error_type,
            "is_retryable": is_retryable,
        }

    # =========================================================================
    # Sleep state management (for @step decorator and EventReplayer compatibility)
    # =========================================================================

    @property
    def pending_sleeps(self) -> dict[str, Any]:
        """Get pending sleeps (sleep_id -> resume_at)."""
        return self._pending_sleeps

    def add_pending_sleep(self, sleep_id: str, resume_at: Any) -> None:
        """Add a pending sleep."""
        self._pending_sleeps[sleep_id] = resume_at

    def mark_sleep_completed(self, sleep_id: str) -> None:
        """Mark a sleep as completed."""
        self._completed_sleeps.add(sleep_id)

    def should_execute_sleep(self, sleep_id: str) -> bool:
        """Check if a sleep should be executed (not already completed)."""
        return sleep_id not in self._completed_sleeps

    def is_sleep_completed(self, sleep_id: str) -> bool:
        """Check if a sleep has been completed."""
        return sleep_id in self._completed_sleeps

    @property
    def completed_sleeps(self) -> set[str]:
        """Get the set of completed sleep IDs."""
        return self._completed_sleeps

    # =========================================================================
    # Hook state management (for EventReplayer compatibility)
    # =========================================================================

    @property
    def pending_hooks(self) -> dict[str, Any]:
        """Get pending hooks."""
        return self._pending_hooks

    def add_pending_hook(self, hook_id: str, data: Any) -> None:
        """Add a pending hook."""
        self._pending_hooks[hook_id] = data

    def cache_hook_result(self, hook_id: str, payload: Any) -> None:
        """Cache a hook result."""
        self._hook_results[hook_id] = payload

    def has_hook_result(self, hook_id: str) -> bool:
        """Check if a hook result exists."""
        return hook_id in self._hook_results

    def get_hook_result(self, hook_id: str) -> Any:
        """Get a cached hook result."""
        return self._hook_results.get(hook_id)

    # =========================================================================
    # Child workflow state management
    # =========================================================================

    @property
    def pending_children(self) -> dict[str, str]:
        """Get pending child workflows (child_id -> child_run_id)."""
        return self._pending_children

    @property
    def child_results(self) -> dict[str, dict[str, Any]]:
        """Get child workflow results."""
        return self._child_results

    def has_child_result(self, child_id: str) -> bool:
        """Check if a child workflow result exists."""
        return child_id in self._child_results

    def get_child_result(self, child_id: str) -> dict[str, Any]:
        """Get cached child workflow result."""
        return self._child_results.get(child_id, {})

    def cache_child_result(
        self,
        child_id: str,
        child_run_id: str,
        result: Any,
        failed: bool = False,
        error: str | None = None,
        error_type: str | None = None,
    ) -> None:
        """
        Cache a child workflow result.

        Args:
            child_id: Deterministic child identifier
            child_run_id: The child workflow's run ID
            result: The result (if successful)
            failed: Whether the child failed
            error: Error message (if failed)
            error_type: Exception type (if failed)
        """
        if failed:
            self._child_results[child_id] = {
                "child_run_id": child_run_id,
                "error": error,
                "error_type": error_type,
                "__failed__": True,
            }
        else:
            self._child_results[child_id] = {
                "child_run_id": child_run_id,
                "result": result,
                "__failed__": False,
            }
        self._pending_children.pop(child_id, None)

    def add_pending_child(self, child_id: str, child_run_id: str) -> None:
        """Add a pending child workflow."""
        self._pending_children[child_id] = child_run_id

    # =========================================================================
    # Event log access (for EventReplayer compatibility)
    # =========================================================================

    @property
    def event_log(self) -> list[Any]:
        """Get the event log."""
        return self._event_log

    @event_log.setter
    def event_log(self, events: list[Any]) -> None:
        """Set the event log."""
        self._event_log = events

    @property
    def step_results(self) -> dict[str, Any]:
        """Get step results."""
        return self._step_results

    @property
    def hook_results(self) -> dict[str, Any]:
        """Get hook results."""
        return self._hook_results

    @property
    def retry_state(self) -> dict[str, dict[str, Any]]:
        """Get retry states."""
        return self._retry_states

    # =========================================================================
    # Event limit validation
    # =========================================================================

    async def validate_event_limits(self) -> None:
        """
        Validate event count against configured soft/hard limits.

        - Soft limit: Log warning, then every N events after
        - Hard limit: Raise EventLimitExceededError

        Called before recording new events to prevent runaway workflows.

        Raises:
            EventLimitExceededError: If event count exceeds hard limit
        """
        if not self._durable or self._storage is None:
            return  # Skip validation for transient mode

        from pyworkflow.config import get_config
        from pyworkflow.core.exceptions import EventLimitExceededError

        config = get_config()

        # Get current event count from storage
        events = await self._get_storage().get_events(self._run_id)
        event_count = len(events)

        # Hard limit check - fail immediately
        if event_count >= config.event_hard_limit:
            raise EventLimitExceededError(self._run_id, event_count, config.event_hard_limit)

        # Soft limit check with interval warnings
        if event_count >= config.event_soft_limit:
            # Calculate if we should log a warning
            should_warn = (
                self._last_warning_count == 0  # First warning
                or event_count >= self._last_warning_count + config.event_warning_interval
            )

            if should_warn:
                logger.warning(
                    f"Workflow approaching event limit: {event_count}/{config.event_hard_limit}",
                    run_id=self._run_id,
                    event_count=event_count,
                    soft_limit=config.event_soft_limit,
                    hard_limit=config.event_hard_limit,
                )
                self._last_warning_count = event_count

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
        step_name: str = name or getattr(func, "__name__", None) or "step"

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
            await self._record_step_complete(step_id, step_name, result)

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
        await self._get_storage().record_event(event)

    async def _record_step_complete(self, step_id: str, step_name: str, result: Any) -> None:
        """Record step completed event."""
        from pyworkflow.engine.events import create_step_completed_event
        from pyworkflow.serialization.encoder import serialize

        event = create_step_completed_event(
            run_id=self._run_id,
            step_id=step_id,
            result=serialize(result),
            step_name=step_name,
        )
        await self._get_storage().record_event(event)

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
        await self._get_storage().record_event(event)

    # =========================================================================
    # Sleep
    # =========================================================================

    async def sleep(self, duration: str | int | float) -> None:
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
        duration_seconds = parse_duration(duration) if isinstance(duration, str) else int(duration)

        if not self._durable:
            # Transient mode - just sleep
            logger.debug(f"[transient] Sleeping {duration_seconds}s")
            await asyncio.sleep(duration_seconds)
            return

        # Check for cancellation before sleeping
        self.check_cancellation()

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

        # Validate event limits before recording sleep event
        await self.validate_event_limits()

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
        await self._get_storage().record_event(event)

    # =========================================================================
    # Parallel execution
    # =========================================================================

    async def parallel(self, *tasks: Any) -> list[Any]:
        """Execute multiple tasks in parallel."""
        return list(await asyncio.gather(*tasks))

    # =========================================================================
    # External events (hooks)
    # =========================================================================

    async def wait_for_event(
        self,
        event_name: str,
        timeout: str | int | None = None,
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
            raise NotImplementedError("wait_for_event requires durable mode with storage")

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
        self, hook_id: str, event_name: str, timeout: str | int | None
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
        await self._get_storage().record_event(event)

    async def hook(
        self,
        name: str,
        timeout: int | None = None,
        on_created: Callable[[str], Awaitable[None]] | None = None,
        payload_schema: type[BaseModel] | None = None,
    ) -> Any:
        """
        Wait for an external event (webhook, approval, callback).

        In durable mode:
        - Generates hook_id and composite token (run_id:hook_id)
        - Checks if already received (replay mode)
        - Records HOOK_CREATED event (idempotency checked via events)
        - Calls on_created callback with token (if provided)
        - Raises SuspensionSignal to pause workflow

        In transient mode:
        - Raises NotImplementedError (hooks require durability)

        Args:
            name: Human-readable name for the hook
            timeout: Optional timeout in seconds
            on_created: Optional async callback called with token when hook is created
            payload_schema: Optional Pydantic model class for payload validation

        Returns:
            Payload from resume_hook()

        Raises:
            NotImplementedError: If not in durable mode
        """
        if not self._durable:
            raise NotImplementedError(
                "hook() requires durable mode with storage. "
                "Initialize LocalContext with durable=True and a storage backend."
            )

        # Check for cancellation before waiting for hook
        self.check_cancellation()

        # Generate deterministic hook_id
        self._step_counter += 1
        hook_id = f"hook_{name}_{self._step_counter}"

        # Check if already received (replay mode)
        if hook_id in self._hook_results:
            logger.debug(f"[replay] Hook {hook_id} already received")
            return self._hook_results[hook_id]

        # Generate composite token: run_id:hook_id
        from pyworkflow.primitives.resume_hook import create_hook_token

        actual_token = create_hook_token(self._run_id, hook_id)

        # Calculate expiration time
        expires_at = None
        if timeout:
            expires_at = datetime.now(UTC) + timedelta(seconds=timeout)

        # Validate event limits before recording hook event
        await self.validate_event_limits()

        # Record HOOK_CREATED event (this is the source of truth for hook existence)
        from pyworkflow.engine.events import create_hook_created_event

        event = create_hook_created_event(
            run_id=self._run_id,
            hook_id=hook_id,
            hook_name=name,
            token=actual_token,
            timeout_seconds=timeout,
            expires_at=expires_at,
        )
        await self._get_storage().record_event(event)

        # Convert Pydantic model to JSON schema if provided
        schema_json = None
        if payload_schema is not None:
            schema_json = json.dumps(payload_schema.model_json_schema())

        # Create Hook record in storage for querying
        from pyworkflow.storage.schemas import Hook

        hook_record = Hook(
            hook_id=hook_id,
            run_id=self._run_id,
            token=actual_token,
            name=name,
            expires_at=expires_at,
            payload_schema=schema_json,
        )
        await self._get_storage().create_hook(hook_record)

        # Track pending hook locally
        self._pending_hooks[hook_id] = {
            "token": actual_token,
            "name": name,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }

        # Call on_created callback if provided (before suspension)
        if on_created is not None:
            await on_created(actual_token)

        logger.info(
            f"Waiting for hook: {name}",
            run_id=self._run_id,
            hook_id=hook_id,
            token=actual_token,
        )

        raise SuspensionSignal(
            reason=f"hook:{hook_id}",
            hook_id=hook_id,
            token=actual_token,
        )

    # =========================================================================
    # Cancellation support
    # =========================================================================

    def is_cancellation_requested(self) -> bool:
        """
        Check if cancellation has been requested for this workflow.

        Returns:
            True if cancellation was requested, False otherwise
        """
        return self._cancellation_requested

    def request_cancellation(self, reason: str | None = None) -> None:
        """
        Mark this workflow as cancelled.

        This sets the cancellation flag. The workflow will raise
        CancellationError at the next cancellation check point.

        Args:
            reason: Optional reason for cancellation
        """
        self._cancellation_requested = True
        self._cancellation_reason = reason
        logger.info(
            "Cancellation requested for workflow",
            run_id=self._run_id,
            reason=reason,
        )

    def check_cancellation(self) -> None:
        """
        Check for cancellation and raise if requested.

        This should be called at interruptible points (before steps,
        during sleeps, etc.) to allow graceful cancellation.

        Raises:
            CancellationError: If cancellation was requested and not blocked
        """
        if self._cancellation_requested and not self._cancellation_blocked:
            from pyworkflow.core.exceptions import CancellationError

            logger.info(
                "Cancellation check triggered - raising CancellationError",
                run_id=self._run_id,
                reason=self._cancellation_reason,
            )
            raise CancellationError(
                message=f"Workflow was cancelled: {self._cancellation_reason or 'no reason provided'}",
                reason=self._cancellation_reason,
            )

    @property
    def cancellation_blocked(self) -> bool:
        """
        Check if cancellation is currently blocked (within a shield scope).

        Returns:
            True if cancellation is blocked, False otherwise
        """
        return self._cancellation_blocked

    @property
    def cancellation_reason(self) -> str | None:
        """
        Get the reason for cancellation, if any.

        Returns:
            The cancellation reason or None if not cancelled
        """
        return self._cancellation_reason
