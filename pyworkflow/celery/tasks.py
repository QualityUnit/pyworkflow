"""
Celery tasks for distributed workflow and step execution.

These tasks enable:
- Distributed step execution across workers
- Automatic retry with exponential backoff and jitter (via Celery)
- Scheduled sleep resumption
- Workflow orchestration
- Fault tolerance with automatic recovery on worker failures
"""

import asyncio
import random
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyworkflow.context.step_context import StepContext

from celery.exceptions import MaxRetriesExceededError, Retry
from loguru import logger

from pyworkflow.celery.app import celery_app
from pyworkflow.celery.loop import run_async
from pyworkflow.celery.singleton import SingletonWorkflowTask
from pyworkflow.core.exceptions import (
    CancellationError,
    ContinueAsNewSignal,
    FatalError,
    RetryableError,
    SuspensionSignal,
)
from pyworkflow.core.registry import WorkflowMetadata, get_workflow
from pyworkflow.core.validation import validate_step_parameters
from pyworkflow.core.workflow import execute_workflow_with_context
from pyworkflow.engine.events import (
    EventType,
    create_child_workflow_cancelled_event,
    create_workflow_cancelled_event,
    create_workflow_continued_as_new_event,
    create_workflow_interrupted_event,
    create_workflow_started_event,
    create_workflow_suspended_event,
)
from pyworkflow.serialization.decoder import deserialize_args, deserialize_kwargs
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


def _calculate_exponential_backoff(
    attempt: int, base: float = 2.0, max_delay: float = 300.0
) -> float:
    """
    Calculate exponential backoff delay with jitter.

    Args:
        attempt: Current retry attempt (0-indexed)
        base: Base delay multiplier (default: 2.0)
        max_delay: Maximum delay in seconds (default: 300s / 5 minutes)

    Returns:
        Delay in seconds with jitter applied

    Formula: min(base * 2^attempt, max_delay) * (0.5 + random(0, 0.5))
    This gives delays like: ~1s, ~2s, ~4s, ~8s, ~16s, ... capped at max_delay
    """
    delay = min(base * (2**attempt), max_delay)
    # Add jitter: multiply by random factor between 0.5 and 1.0
    # This prevents thundering herd when multiple tasks retry simultaneously
    jitter = 0.5 + random.random() * 0.5
    return delay * jitter


@celery_app.task(
    name="pyworkflow.execute_step",
    base=SingletonWorkflowTask,
    bind=True,
    queue="pyworkflow.steps",
    unique_on=["run_id", "step_id"],
)
def execute_step_task(
    self: SingletonWorkflowTask,
    step_name: str,
    args_json: str,
    kwargs_json: str,
    run_id: str,
    step_id: str,
    max_retries: int = 3,
    storage_config: dict[str, Any] | None = None,
    context_data: dict[str, Any] | None = None,
    context_class_name: str | None = None,
) -> Any:
    """
    Execute a workflow step on a Celery worker.

    This task:
    1. Executes the step function
    2. Records STEP_COMPLETED/STEP_FAILED event in storage
    3. Triggers workflow resumption via resume_workflow_task

    Args:
        step_name: Name of the step function
        args_json: Serialized positional arguments
        kwargs_json: Serialized keyword arguments
        run_id: Workflow run ID
        step_id: Step execution ID
        max_retries: Maximum retry attempts
        storage_config: Storage backend configuration
        context_data: Optional step context data (from workflow)
        context_class_name: Optional fully qualified context class name

    Returns:
        Step result (serialized)

    Raises:
        FatalError: For non-retriable errors after all retries exhausted
    """
    # Ensure logging is configured in forked worker process
    from pyworkflow.celery.app import _configure_worker_logging

    _configure_worker_logging()

    from pyworkflow.core.registry import _registry

    logger.info(
        f"Executing dispatched step: {step_name}",
        run_id=run_id,
        step_id=step_id,
        attempt=self.request.retries + 1,
    )

    # Check workflow status before executing - bail out if workflow is in terminal state
    storage = _get_storage_backend(storage_config)
    run = run_async(_get_workflow_run_safe(storage, run_id))
    if run is None:
        logger.warning(
            f"Workflow run not found, skipping step execution: {step_name}",
            run_id=run_id,
            step_id=step_id,
        )
        return None

    # Only proceed if workflow is in a state where step execution makes sense
    if run.status not in (RunStatus.RUNNING, RunStatus.SUSPENDED):
        logger.warning(
            f"Workflow in terminal state ({run.status.value}), skipping step execution: {step_name}",
            run_id=run_id,
            step_id=step_id,
            workflow_status=run.status.value,
        )
        return None

    # Get step metadata
    step_meta = _registry.get_step(step_name)
    if not step_meta:
        # Record failure and resume workflow
        run_async(
            _record_step_failure_and_resume(
                storage_config=storage_config,
                run_id=run_id,
                step_id=step_id,
                step_name=step_name,
                error=f"Step '{step_name}' not found in registry",
                error_type="FatalError",
                is_retryable=False,
            )
        )
        raise FatalError(f"Step '{step_name}' not found in registry")

    # Ignore processing step if already completed (idempotency)
    events = run_async(storage.get_events(run_id))
    already_completed = any(
        evt.type == EventType.STEP_COMPLETED and evt.data.get("step_id") == step_id
        for evt in events
    )
    if already_completed:
        logger.warning(
            "Step already completed by another task, skipping execution",
            run_id=run_id,
            step_id=step_id,
            step_name=step_name,
        )
        return None

    # Deserialize arguments
    args = deserialize_args(args_json)
    kwargs = deserialize_kwargs(kwargs_json)

    # Validate parameters before execution on worker (defense in depth)
    validate_step_parameters(step_meta.original_func, args, kwargs, step_name)

    # Set up step context if provided (read-only mode)
    step_context_token = None
    readonly_token = None

    if context_data and context_class_name:
        try:
            from pyworkflow.context.step_context import (
                _set_step_context_internal,
                _set_step_context_readonly,
            )

            # Import context class dynamically
            context_class = _resolve_context_class(context_class_name)
            if context_class is not None:
                step_ctx = context_class.from_dict(context_data)
                step_context_token = _set_step_context_internal(step_ctx)
                # Set readonly mode to prevent mutation in steps
                readonly_token = _set_step_context_readonly(True)
        except Exception as e:
            logger.warning(
                f"Failed to load step context: {e}",
                run_id=run_id,
                step_id=step_id,
            )

    # Execute step function
    try:
        # Get the original function (unwrapped from decorator)
        step_func = step_meta.original_func

        # Execute the step
        if asyncio.iscoroutinefunction(step_func):
            result = run_async(step_func(*args, **kwargs))
        else:
            result = step_func(*args, **kwargs)

        logger.info(
            f"Step completed: {step_name}",
            run_id=run_id,
            step_id=step_id,
        )

        # Record STEP_COMPLETED event and trigger workflow resumption
        run_async(
            _record_step_completion_and_resume(
                storage_config=storage_config,
                run_id=run_id,
                step_id=step_id,
                step_name=step_name,
                result=result,
            )
        )

        return result

    except Retry:
        # Celery retry in progress - let it propagate correctly
        raise

    except MaxRetriesExceededError:
        # Celery hit its internal retry limit - treat as fatal
        logger.error(
            f"Step exceeded Celery retry limit: {step_name}",
            run_id=run_id,
            step_id=step_id,
        )
        raise

    except FatalError as e:
        logger.error(f"Step failed (fatal): {step_name}", run_id=run_id, step_id=step_id)
        # Record failure and resume workflow (workflow will fail on replay)
        run_async(
            _record_step_failure_and_resume(
                storage_config=storage_config,
                run_id=run_id,
                step_id=step_id,
                step_name=step_name,
                error=str(e),
                error_type=type(e).__name__,
                is_retryable=False,
            )
        )
        raise

    except RetryableError as e:
        # Check if we have retries left
        if self.request.retries < max_retries:
            # Use explicit retry_after if provided, otherwise use exponential backoff
            countdown = (
                e.retry_after
                if e.retry_after
                else _calculate_exponential_backoff(self.request.retries)
            )
            logger.warning(
                f"Step failed (retriable): {step_name}, retrying in {countdown:.1f}s...",
                run_id=run_id,
                step_id=step_id,
                countdown=countdown,
                attempt=self.request.retries + 1,
                max_retries=max_retries,
            )
            # Let Celery handle the retry - don't resume workflow yet
            raise self.retry(countdown=countdown, exc=e)
        else:
            # Max retries exhausted - record failure and resume workflow
            logger.error(
                f"Step failed after {max_retries + 1} attempts: {step_name}",
                run_id=run_id,
                step_id=step_id,
            )
            run_async(
                _record_step_failure_and_resume(
                    storage_config=storage_config,
                    run_id=run_id,
                    step_id=step_id,
                    step_name=step_name,
                    error=str(e),
                    error_type=type(e).__name__,
                    is_retryable=False,  # Mark as not retryable since we exhausted retries
                )
            )
            raise FatalError(f"Step '{step_name}' failed after retries: {str(e)}") from e

    except Exception as e:
        # Check if we have retries left
        if self.request.retries < max_retries:
            # Use exponential backoff for unexpected errors
            countdown = _calculate_exponential_backoff(self.request.retries)
            logger.warning(
                f"Step failed (unexpected): {step_name}, retrying in {countdown:.1f}s...: {str(e)}",
                run_id=run_id,
                step_id=step_id,
                error=str(e),
                countdown=countdown,
                attempt=self.request.retries + 1,
            )
            # Treat unexpected errors as retriable with exponential backoff
            raise self.retry(exc=e, countdown=countdown)
        else:
            # Max retries exhausted
            logger.error(
                f"Step failed after {max_retries + 1} attempts: {step_name}",
                run_id=run_id,
                step_id=step_id,
                error=str(e),
                exc_info=True,
            )
            run_async(
                _record_step_failure_and_resume(
                    storage_config=storage_config,
                    run_id=run_id,
                    step_id=step_id,
                    step_name=step_name,
                    error=str(e),
                    error_type=type(e).__name__,
                    is_retryable=False,
                )
            )
            raise FatalError(f"Step '{step_name}' failed after retries: {str(e)}") from e

    finally:
        # Clean up step context
        if readonly_token is not None:
            from pyworkflow.context.step_context import _reset_step_context_readonly

            _reset_step_context_readonly(readonly_token)
        if step_context_token is not None:
            from pyworkflow.context.step_context import _reset_step_context

            _reset_step_context(step_context_token)


async def _record_step_completion_and_resume(
    storage_config: dict[str, Any] | None,
    run_id: str,
    step_id: str,
    step_name: str,
    result: Any,
) -> None:
    """
    Record STEP_COMPLETED event and trigger workflow resumption if safe.

    Called by execute_step_task after successful step execution.

    Only schedules resume if WORKFLOW_SUSPENDED event exists, indicating
    the workflow has fully suspended. This prevents race conditions where
    a step completes before the workflow has suspended.

    Idempotency: If STEP_COMPLETED already exists for this step_id, skip
    recording and resume scheduling (another task already handled it).
    """
    from pyworkflow.engine.events import create_step_completed_event
    from pyworkflow.serialization.encoder import serialize

    # Get storage backend
    storage = _get_storage_backend(storage_config)

    # Ensure storage is connected
    if hasattr(storage, "connect"):
        await storage.connect()

    # Idempotency check: skip if step already completed
    events = await storage.get_events(run_id)
    already_completed = any(
        evt.type == EventType.STEP_COMPLETED and evt.data.get("step_id") == step_id
        for evt in events
    )
    if already_completed:
        logger.info(
            "Step already completed by another task, skipping",
            run_id=run_id,
            step_id=step_id,
            step_name=step_name,
        )
        return

    # Record STEP_COMPLETED event
    completion_event = create_step_completed_event(
        run_id=run_id,
        step_id=step_id,
        result=serialize(result),
        step_name=step_name,
    )
    await storage.record_event(completion_event)

    # Refresh events to include the one we just recorded
    events = await storage.get_events(run_id)

    # Check if workflow has suspended (WORKFLOW_SUSPENDED event exists)
    # Only schedule resume if workflow has properly suspended
    has_suspended = any(evt.type == EventType.WORKFLOW_SUSPENDED for evt in events)

    if has_suspended:
        # Workflow has suspended, safe to schedule resume
        schedule_workflow_resumption(
            run_id, datetime.now(UTC), storage_config, triggered_by="step_completed"
        )
        logger.info(
            "Step completed and workflow resumption scheduled",
            run_id=run_id,
            step_id=step_id,
            step_name=step_name,
        )
    else:
        # Workflow hasn't suspended yet - don't schedule resume
        # The suspension handler will check for step completion and schedule resume
        logger.info(
            "Step completed but workflow not yet suspended, skipping resume scheduling",
            run_id=run_id,
            step_id=step_id,
            step_name=step_name,
        )


async def _record_step_failure_and_resume(
    storage_config: dict[str, Any] | None,
    run_id: str,
    step_id: str,
    step_name: str,
    error: str,
    error_type: str,
    is_retryable: bool,
) -> None:
    """
    Record STEP_FAILED event and trigger workflow resumption if safe.

    Called by execute_step_task after step failure (when retries are exhausted).
    The workflow will fail when it replays and sees the failure event.

    Only schedules resume if WORKFLOW_SUSPENDED event exists, indicating
    the workflow has fully suspended. This prevents race conditions where
    a step fails before the workflow has suspended.

    Idempotency: If STEP_COMPLETED or terminal STEP_FAILED already exists
    for this step_id, skip recording and resume scheduling.
    """
    from pyworkflow.engine.events import create_step_failed_event

    # Get storage backend
    storage = _get_storage_backend(storage_config)

    # Ensure storage is connected
    if hasattr(storage, "connect"):
        await storage.connect()

    # Idempotency check: skip if step already completed or terminally failed
    events = await storage.get_events(run_id)
    already_handled = any(
        (evt.type == EventType.STEP_COMPLETED and evt.data.get("step_id") == step_id)
        or (
            evt.type == EventType.STEP_FAILED
            and evt.data.get("step_id") == step_id
            and not evt.data.get("is_retryable", True)
        )
        for evt in events
    )
    if already_handled:
        logger.info(
            "Step already completed/failed by another task, skipping",
            run_id=run_id,
            step_id=step_id,
            step_name=step_name,
        )
        return

    # Record STEP_FAILED event
    failure_event = create_step_failed_event(
        run_id=run_id,
        step_id=step_id,
        error=error,
        error_type=error_type,
        is_retryable=is_retryable,
        attempt=1,  # Final attempt
    )
    await storage.record_event(failure_event)

    # Refresh events to include the one we just recorded
    events = await storage.get_events(run_id)

    # Check if workflow has suspended (WORKFLOW_SUSPENDED event exists)
    # Only schedule resume if workflow has properly suspended
    has_suspended = any(evt.type == EventType.WORKFLOW_SUSPENDED for evt in events)

    if has_suspended:
        # Workflow has suspended, safe to schedule resume
        schedule_workflow_resumption(
            run_id, datetime.now(UTC), storage_config, triggered_by="step_failed"
        )
        logger.info(
            "Step failed and workflow resumption scheduled",
            run_id=run_id,
            step_id=step_id,
            step_name=step_name,
            error=error,
        )
    else:
        # Workflow hasn't suspended yet - don't schedule resume
        # The suspension handler will check for step failure and schedule resume
        logger.info(
            "Step failed but workflow not yet suspended, skipping resume scheduling",
            run_id=run_id,
            step_id=step_id,
            step_name=step_name,
            error=error,
        )


async def _get_workflow_run_safe(
    storage: StorageBackend,
    run_id: str,
) -> WorkflowRun | None:
    """
    Safely get workflow run with proper storage connection handling.

    Args:
        storage: Storage backend
        run_id: Workflow run ID

    Returns:
        WorkflowRun or None if not found
    """
    if hasattr(storage, "connect"):
        await storage.connect()
    return await storage.get_run(run_id)


def _resolve_context_class(class_name: str) -> type["StepContext"] | None:
    """
    Resolve a context class from its fully qualified name.

    Args:
        class_name: Fully qualified class name (e.g., "myapp.contexts.OrderContext")

    Returns:
        The class type, or None if resolution fails
    """
    try:
        import importlib

        parts = class_name.rsplit(".", 1)
        if len(parts) == 2:
            module_name, cls_name = parts
            module = importlib.import_module(module_name)
            return getattr(module, cls_name, None)
        # Simple class name - try to get from globals
        return None
    except Exception:
        return None


@celery_app.task(
    name="pyworkflow.start_workflow",
    base=SingletonWorkflowTask,
    queue="pyworkflow.workflows",
    unique_on=["run_id"],
)
def start_workflow_task(
    workflow_name: str,
    args_json: str,
    kwargs_json: str,
    run_id: str,
    storage_config: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> str:
    """
    Start a workflow execution.

    This task executes on Celery workers and runs the workflow directly.

    Args:
        workflow_name: Name of the workflow
        args_json: Serialized positional arguments
        kwargs_json: Serialized keyword arguments
        run_id: Workflow run ID (generated by the caller)
        storage_config: Storage backend configuration
        idempotency_key: Optional idempotency key

    Returns:
        Workflow run ID
    """
    # Ensure logging is configured in forked worker process
    from pyworkflow.celery.app import _configure_worker_logging

    _configure_worker_logging()

    logger.info(
        f"START_WORKFLOW_TASK ENTRY: {workflow_name}",
        run_id=run_id,
        idempotency_key=idempotency_key,
        celery_task_id=start_workflow_task.request.id,
    )

    # Get workflow metadata
    workflow_meta = get_workflow(workflow_name)
    if not workflow_meta:
        raise ValueError(f"Workflow '{workflow_name}' not found in registry")

    # Deserialize arguments
    args = deserialize_args(args_json)
    kwargs = deserialize_kwargs(kwargs_json)

    # Get storage backend
    storage = _get_storage_backend(storage_config)

    # Execute workflow directly on worker
    result_run_id = run_async(
        _start_workflow_on_worker(
            workflow_meta=workflow_meta,
            args=args,
            kwargs=kwargs,
            storage=storage,
            storage_config=storage_config,
            idempotency_key=idempotency_key,
            run_id=run_id,
        )
    )

    logger.info(f"Workflow execution initiated: {workflow_name}", run_id=result_run_id)
    return result_run_id


@celery_app.task(
    name="pyworkflow.start_child_workflow",
    base=SingletonWorkflowTask,
    queue="pyworkflow.workflows",
    unique_on=["child_run_id"],
)
def start_child_workflow_task(
    workflow_name: str,
    args_json: str,
    kwargs_json: str,
    child_run_id: str,
    storage_config: dict[str, Any] | None,
    parent_run_id: str,
    child_id: str,
    wait_for_completion: bool,
) -> str:
    """
    Start a child workflow execution on Celery worker.

    This task executes child workflows and handles parent notification
    when the child completes or fails.

    Args:
        workflow_name: Name of the child workflow
        args_json: Serialized positional arguments
        kwargs_json: Serialized keyword arguments
        child_run_id: Child workflow run ID (already created by parent)
        storage_config: Storage backend configuration
        parent_run_id: Parent workflow run ID
        child_id: Deterministic child ID for replay
        wait_for_completion: Whether parent is waiting for child

    Returns:
        Child workflow run ID
    """
    # Ensure logging is configured in forked worker process
    from pyworkflow.celery.app import _configure_worker_logging

    _configure_worker_logging()

    logger.info(
        f"Starting child workflow on worker: {workflow_name}",
        child_run_id=child_run_id,
        parent_run_id=parent_run_id,
    )

    # Get workflow metadata
    workflow_meta = get_workflow(workflow_name)
    if not workflow_meta:
        raise ValueError(f"Workflow '{workflow_name}' not found in registry")

    # Deserialize arguments
    args = deserialize_args(args_json)
    kwargs = deserialize_kwargs(kwargs_json)

    # Get storage backend
    storage = _get_storage_backend(storage_config)

    # Execute child workflow on worker
    run_async(
        _execute_child_workflow_on_worker(
            workflow_func=workflow_meta.func,
            workflow_name=workflow_name,
            args=args,
            kwargs=kwargs,
            child_run_id=child_run_id,
            storage=storage,
            storage_config=storage_config,
            parent_run_id=parent_run_id,
            child_id=child_id,
            wait_for_completion=wait_for_completion,
        )
    )

    logger.info(
        f"Child workflow execution completed: {workflow_name}",
        child_run_id=child_run_id,
    )
    return child_run_id


async def _execute_child_workflow_on_worker(
    workflow_func: Callable[..., Any],
    workflow_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    child_run_id: str,
    storage: StorageBackend,
    storage_config: dict[str, Any] | None,
    parent_run_id: str,
    child_id: str,
    wait_for_completion: bool,
) -> None:
    """
    Execute a child workflow on Celery worker and notify parent on completion.

    This handles:
    1. Executing the child workflow
    2. Recording completion/failure events in parent's log
    3. Triggering parent resumption if waiting
    """
    # Ensure storage is connected (some backends like SQLite require this)
    if hasattr(storage, "connect"):
        await storage.connect()

    from pyworkflow.engine.events import (
        create_child_workflow_completed_event,
        create_child_workflow_failed_event,
    )
    from pyworkflow.serialization.encoder import serialize

    try:
        # Update status to RUNNING
        await storage.update_run_status(child_run_id, RunStatus.RUNNING)

        # Execute the child workflow
        result = await execute_workflow_with_context(
            run_id=child_run_id,
            workflow_func=workflow_func,
            workflow_name=workflow_name,
            args=args,
            kwargs=kwargs,
            storage=storage,
            durable=True,
            event_log=None,  # Fresh execution
            runtime="celery",
            storage_config=storage_config,
        )

        # Update status to COMPLETED
        serialized_result = serialize(result)
        await storage.update_run_status(child_run_id, RunStatus.COMPLETED, result=serialized_result)

        # Record completion in parent's log
        completion_event = create_child_workflow_completed_event(
            run_id=parent_run_id,
            child_id=child_id,
            child_run_id=child_run_id,
            result=serialized_result,
        )
        await storage.record_event(completion_event)

        logger.info(
            f"Child workflow completed: {workflow_name}",
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
        )

        # If parent is waiting, trigger resumption
        if wait_for_completion:
            await _trigger_parent_resumption_celery(parent_run_id, storage, storage_config)

    except SuspensionSignal as e:
        # Child workflow suspended (e.g., sleep, hook, step dispatch)
        # Update status and don't notify parent yet - handled on child resumption
        await storage.update_run_status(child_run_id, RunStatus.SUSPENDED)

        # Record WORKFLOW_SUSPENDED event
        step_id = e.data.get("step_id") if e.data else None
        step_name = e.data.get("step_name") if e.data else None
        sleep_id = e.data.get("sleep_id") if e.data else None
        hook_id = e.data.get("hook_id") if e.data else None
        nested_child_id = e.data.get("child_id") if e.data else None

        suspended_event = create_workflow_suspended_event(
            run_id=child_run_id,
            reason=e.reason,
            step_id=step_id,
            step_name=step_name,
            sleep_id=sleep_id,
            hook_id=hook_id,
            child_id=nested_child_id,
        )
        await storage.record_event(suspended_event)

        logger.debug(
            f"Child workflow suspended: {workflow_name}",
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
        )

        # For step dispatch suspensions, check if step already completed/failed
        if step_id and e.reason.startswith("step_dispatch:"):
            events = await storage.get_events(child_run_id)
            step_finished = any(
                evt.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
                and evt.data.get("step_id") == step_id
                for evt in events
            )
            if step_finished:
                logger.info(
                    "Child step finished before suspension completed, scheduling resume",
                    child_run_id=child_run_id,
                    step_id=step_id,
                )
                schedule_workflow_resumption(
                    child_run_id,
                    datetime.now(UTC),
                    storage_config=storage_config,
                    triggered_by="child_suspension_step_race",
                )
                return

        # Schedule automatic resumption if we have a resume_at time
        resume_at = e.data.get("resume_at") if e.data else None
        if resume_at:
            schedule_workflow_resumption(
                child_run_id, resume_at, storage_config, triggered_by="child_sleep_hook"
            )

    except ContinueAsNewSignal as e:
        # Child workflow continuing as new execution
        from pyworkflow.core.registry import get_workflow

        child_workflow_meta = get_workflow(workflow_name)
        if not child_workflow_meta:
            raise ValueError(f"Workflow '{workflow_name}' not found in registry")

        new_run_id = await _handle_continue_as_new_celery(
            current_run_id=child_run_id,
            workflow_meta=child_workflow_meta,
            storage=storage,
            storage_config=storage_config,
            new_args=e.workflow_args,
            new_kwargs=e.workflow_kwargs,
            parent_run_id=parent_run_id,
        )

        logger.info(
            f"Child workflow continued as new: {workflow_name}",
            old_run_id=child_run_id,
            new_run_id=new_run_id,
            parent_run_id=parent_run_id,
        )

    except Exception as e:
        # Child workflow failed
        error_msg = str(e)
        error_type = type(e).__name__

        await storage.update_run_status(child_run_id, RunStatus.FAILED, error=error_msg)

        # Record failure in parent's log
        failure_event = create_child_workflow_failed_event(
            run_id=parent_run_id,
            child_id=child_id,
            child_run_id=child_run_id,
            error=error_msg,
            error_type=error_type,
        )
        await storage.record_event(failure_event)

        logger.error(
            f"Child workflow failed: {workflow_name}",
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            error=error_msg,
        )

        # If parent is waiting, trigger resumption (will raise error on replay)
        if wait_for_completion:
            await _trigger_parent_resumption_celery(parent_run_id, storage, storage_config)


async def _trigger_parent_resumption_celery(
    parent_run_id: str,
    storage: StorageBackend,
    storage_config: dict[str, Any] | None,
) -> None:
    """
    Trigger parent workflow resumption after child completes.

    Checks if parent is suspended and schedules resumption via Celery.
    """
    parent_run = await storage.get_run(parent_run_id)
    if parent_run and parent_run.status == RunStatus.SUSPENDED:
        logger.debug(
            "Triggering parent resumption via Celery",
            parent_run_id=parent_run_id,
        )
        # Schedule immediate resumption via Celery
        schedule_workflow_resumption(
            parent_run_id, datetime.now(UTC), storage_config, triggered_by="child_completed"
        )


async def _notify_parent_of_child_completion(
    run: WorkflowRun,
    storage: StorageBackend,
    storage_config: dict[str, Any] | None,
    status: RunStatus,
    result: str | None = None,
    error: str | None = None,
    error_type: str | None = None,
) -> None:
    """
    Notify parent workflow that a child has completed/failed/cancelled.

    This is called when a child workflow reaches a terminal state during resume.
    It records the appropriate event in the parent's log and triggers resumption
    if the parent was waiting.

    Args:
        run: The child workflow run
        storage: Storage backend
        storage_config: Storage configuration for Celery tasks
        status: Terminal status (COMPLETED, FAILED, CANCELLED)
        result: Serialized result (for COMPLETED)
        error: Error message (for FAILED/CANCELLED)
        error_type: Error type name (for FAILED)
    """
    from pyworkflow.engine.events import (
        create_child_workflow_cancelled_event,
        create_child_workflow_completed_event,
        create_child_workflow_failed_event,
    )

    if not run.parent_run_id:
        return  # Not a child workflow

    parent_run_id = run.parent_run_id
    child_run_id = run.run_id

    # Find child_id and wait_for_completion from parent's events
    parent_events = await storage.get_events(parent_run_id)
    child_id = None
    wait_for_completion = False

    for event in parent_events:
        if (
            event.type == EventType.CHILD_WORKFLOW_STARTED
            and event.data.get("child_run_id") == child_run_id
        ):
            child_id = event.data.get("child_id")
            wait_for_completion = event.data.get("wait_for_completion", False)
            break

    if not child_id:
        logger.warning(
            "Could not find child_id in parent events for resumed child workflow",
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
        )
        return

    # Record appropriate event in parent's log
    if status == RunStatus.COMPLETED:
        event = create_child_workflow_completed_event(
            run_id=parent_run_id,
            child_id=child_id,
            child_run_id=child_run_id,
            result=result,
        )
    elif status == RunStatus.FAILED:
        event = create_child_workflow_failed_event(
            run_id=parent_run_id,
            child_id=child_id,
            child_run_id=child_run_id,
            error=error or "Unknown error",
            error_type=error_type or "Exception",
        )
    elif status == RunStatus.CANCELLED:
        event = create_child_workflow_cancelled_event(
            run_id=parent_run_id,
            child_id=child_id,
            child_run_id=child_run_id,
            reason=error,
        )
    else:
        return  # Not a terminal state we handle

    await storage.record_event(event)

    logger.info(
        f"Notified parent of child workflow {status.value}",
        parent_run_id=parent_run_id,
        child_run_id=child_run_id,
        child_id=child_id,
    )

    # Trigger parent resumption if waiting
    if wait_for_completion:
        await _trigger_parent_resumption_celery(parent_run_id, storage, storage_config)


async def _handle_workflow_recovery(
    run: WorkflowRun,
    storage: StorageBackend,
    worker_id: str | None = None,
) -> bool:
    """
    Handle workflow recovery from worker failure.

    Called when a workflow is found in RUNNING status but we're starting fresh.
    This indicates a previous worker crashed.

    Args:
        run: Existing workflow run record
        storage: Storage backend
        worker_id: ID of the current worker

    Returns:
        True if recovery should proceed, False if max attempts exceeded
    """
    # Check if recovery is enabled for this workflow
    if not run.recover_on_worker_loss:
        logger.warning(
            "Workflow recovery disabled, marking as failed",
            run_id=run.run_id,
            workflow_name=run.workflow_name,
        )
        await storage.update_run_status(
            run_id=run.run_id,
            status=RunStatus.FAILED,
            error="Worker lost and recovery is disabled",
        )
        return False

    # Check recovery attempt limit
    new_attempts = run.recovery_attempts + 1
    if new_attempts > run.max_recovery_attempts:
        logger.error(
            "Workflow exceeded max recovery attempts",
            run_id=run.run_id,
            workflow_name=run.workflow_name,
            recovery_attempts=run.recovery_attempts,
            max_recovery_attempts=run.max_recovery_attempts,
        )
        await storage.update_run_status(
            run_id=run.run_id,
            status=RunStatus.FAILED,
            error=f"Exceeded max recovery attempts ({run.max_recovery_attempts})",
        )
        return False

    # Get last event sequence
    events = await storage.get_events(run.run_id)
    last_event_sequence = max((e.sequence or 0 for e in events), default=0) if events else None

    # Record interruption event
    interrupted_event = create_workflow_interrupted_event(
        run_id=run.run_id,
        reason="worker_lost",
        worker_id=worker_id,
        last_event_sequence=last_event_sequence,
        error="Worker process terminated unexpectedly",
        recovery_attempt=new_attempts,
        recoverable=True,
    )
    await storage.record_event(interrupted_event)

    # Update recovery attempts counter
    # Note: We need to update the run record with the new recovery_attempts count
    run.recovery_attempts = new_attempts
    await storage.update_run_recovery_attempts(run.run_id, new_attempts)

    logger.info(
        "Workflow recovery initiated",
        run_id=run.run_id,
        workflow_name=run.workflow_name,
        recovery_attempt=new_attempts,
        max_recovery_attempts=run.max_recovery_attempts,
    )

    return True


async def _recover_workflow_on_worker(
    run: WorkflowRun,
    workflow_meta: WorkflowMetadata,
    storage: StorageBackend,
    storage_config: dict[str, Any] | None = None,
) -> str:
    """
    Recover a workflow after worker failure.

    This is similar to resuming a suspended workflow, but specifically handles
    the recovery scenario after a worker crash.

    Args:
        run: Existing workflow run record
        workflow_meta: Workflow metadata
        storage: Storage backend
        storage_config: Storage configuration for child tasks

    Returns:
        Workflow run ID
    """
    run_id = run.run_id
    workflow_name = run.workflow_name

    logger.info(
        f"Recovering workflow execution: {workflow_name}",
        run_id=run_id,
        workflow_name=workflow_name,
        recovery_attempt=run.recovery_attempts,
    )

    # Update status to RUNNING (from RUNNING or INTERRUPTED)
    await storage.update_run_status(run_id=run_id, status=RunStatus.RUNNING)

    # Load event log for replay
    events = await storage.get_events(run_id)

    # Complete any pending sleeps (mark them as done before resuming)
    events = await _complete_pending_sleeps(run_id, events, storage)

    # Deserialize arguments
    args = deserialize_args(run.input_args)
    kwargs = deserialize_kwargs(run.input_kwargs)

    # Execute workflow with event replay
    try:
        result = await execute_workflow_with_context(
            workflow_func=workflow_meta.func,
            run_id=run_id,
            workflow_name=workflow_name,
            storage=storage,
            args=args,
            kwargs=kwargs,
            event_log=events,
            runtime="celery",
            storage_config=storage_config,
        )

        # Update run status to completed
        await storage.update_run_status(
            run_id=run_id, status=RunStatus.COMPLETED, result=serialize_args(result)
        )

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.COMPLETED, storage)

        logger.info(
            f"Workflow recovered and completed: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            recovery_attempt=run.recovery_attempts,
        )

        return run_id

    except SuspensionSignal as e:
        # Workflow suspended again (during recovery)
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        # Record WORKFLOW_SUSPENDED event
        step_id = e.data.get("step_id") if e.data else None
        step_name = e.data.get("step_name") if e.data else None
        sleep_id = e.data.get("sleep_id") if e.data else None
        hook_id = e.data.get("hook_id") if e.data else None
        child_id = e.data.get("child_id") if e.data else None

        suspended_event = create_workflow_suspended_event(
            run_id=run_id,
            reason=e.reason,
            step_id=step_id,
            step_name=step_name,
            sleep_id=sleep_id,
            hook_id=hook_id,
            child_id=child_id,
        )
        await storage.record_event(suspended_event)

        logger.info(
            f"Recovered workflow suspended: {e.reason}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )

        # For step dispatch suspensions, check if step already completed/failed
        if step_id and e.reason.startswith("step_dispatch:"):
            events = await storage.get_events(run_id)
            step_finished = any(
                evt.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
                and evt.data.get("step_id") == step_id
                for evt in events
            )
            if step_finished:
                logger.info(
                    "Step finished before recovery suspension completed, scheduling resume",
                    run_id=run_id,
                    step_id=step_id,
                )
                schedule_workflow_resumption(
                    run_id,
                    datetime.now(UTC),
                    storage_config=storage_config,
                    triggered_by="recovery_suspension_step_race",
                )
                return run_id

        # Schedule automatic resumption if we have a resume_at time
        resume_at = e.data.get("resume_at") if e.data else None
        if resume_at:
            schedule_workflow_resumption(
                run_id, resume_at, storage_config=storage_config, triggered_by="recovery_sleep_hook"
            )
            logger.info(
                "Scheduled automatic workflow resumption",
                run_id=run_id,
                resume_at=resume_at.isoformat(),
            )

        return run_id

    except ContinueAsNewSignal as e:
        # Workflow continuing as new execution
        new_run_id = await _handle_continue_as_new_celery(
            current_run_id=run_id,
            workflow_meta=workflow_meta,
            storage=storage,
            storage_config=storage_config,
            new_args=e.workflow_args,
            new_kwargs=e.workflow_kwargs,
        )

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.CONTINUED_AS_NEW, storage)

        logger.info(
            f"Recovered workflow continued as new: {workflow_name}",
            old_run_id=run_id,
            new_run_id=new_run_id,
        )

        return run_id

    except Exception as e:
        # Workflow failed during recovery
        await storage.update_run_status(run_id=run_id, status=RunStatus.FAILED, error=str(e))

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.FAILED, storage)

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.FAILED, storage)

        logger.error(
            f"Workflow failed during recovery: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            error=str(e),
            exc_info=True,
        )

        raise


async def _start_workflow_on_worker(
    workflow_meta: WorkflowMetadata,
    args: tuple,
    kwargs: dict,
    storage: StorageBackend,
    storage_config: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    run_id: str | None = None,
) -> str:
    """
    Internal function to start workflow on Celery worker.

    This mirrors the logic from testing.py but runs on workers.
    Handles recovery scenarios when picking up a task from a crashed worker.

    Args:
        workflow_meta: Workflow metadata
        args: Workflow positional arguments
        kwargs: Workflow keyword arguments
        storage: Storage backend
        storage_config: Storage configuration for child tasks
        idempotency_key: Optional idempotency key
        run_id: Pre-generated run ID (if None, generates a new one)
    """
    from pyworkflow.config import get_config

    # Ensure storage is connected (some backends like SQLite require this)
    if hasattr(storage, "connect"):
        await storage.connect()

    workflow_name = workflow_meta.name
    config = get_config()

    run = await storage.get_run(run_id) if run_id else None
    logger.debug(
        f"_START_WORKFLOW_ON_WORKER ENTRY: {workflow_name} with run_id={run_id} and status={run.status.value if run else 'N/A'}",
        run_id=run_id,
    )

    # Check idempotency key
    if idempotency_key:
        existing_run = await storage.get_run_by_idempotency_key(idempotency_key)
        if existing_run:
            logger.info(
                "IDEMPOTENCY CHECK: Found existing run",
                run_id=existing_run.run_id,
                status=existing_run.status.value,
                idempotency_key=idempotency_key,
            )
            # Check if this is a recovery scenario (workflow was RUNNING but worker crashed)
            if existing_run.status == RunStatus.RUNNING:
                # Check if this is truly a crashed worker or just a duplicate task execution
                from datetime import timedelta

                run_age = datetime.now(UTC) - existing_run.created_at
                if run_age < timedelta(seconds=30):
                    logger.info(
                        f"Run with idempotency key '{idempotency_key}' already exists and was created recently. "
                        "Likely duplicate task execution, skipping.",
                        run_id=existing_run.run_id,
                    )
                    return existing_run.run_id

                # This is a recovery scenario - worker crashed while running
                can_recover = await _handle_workflow_recovery(
                    run=existing_run,
                    storage=storage,
                    worker_id=None,  # TODO: Get actual worker ID from Celery
                )
                if can_recover:
                    # Continue with recovery - resume workflow from last checkpoint
                    return await _recover_workflow_on_worker(
                        run=existing_run,
                        workflow_meta=workflow_meta,
                        storage=storage,
                        storage_config=storage_config,
                    )
                else:
                    # Recovery disabled or max attempts exceeded
                    return existing_run.run_id
            elif existing_run.status == RunStatus.INTERRUPTED:
                # Previous recovery attempt also failed, try again
                can_recover = await _handle_workflow_recovery(
                    run=existing_run,
                    storage=storage,
                    worker_id=None,
                )
                if can_recover:
                    return await _recover_workflow_on_worker(
                        run=existing_run,
                        workflow_meta=workflow_meta,
                        storage=storage,
                        storage_config=storage_config,
                    )
                else:
                    return existing_run.run_id
            else:
                # Workflow already completed/failed/etc
                logger.info(
                    f"Workflow with idempotency key '{idempotency_key}' already exists",
                    run_id=existing_run.run_id,
                    status=existing_run.status.value,
                )
                return existing_run.run_id

    # Use provided run_id or generate a new one
    if run_id is None:
        run_id = f"run_{uuid.uuid4().hex[:16]}"

    # Check if run already exists
    existing_run = await storage.get_run(run_id)
    if existing_run:
        logger.info(
            f"RUN_ID CHECK: Found existing run with status {existing_run.status.value}",
            run_id=run_id,
            status=existing_run.status.value,
        )

        if existing_run.status == RunStatus.RUNNING:
            # Recovery scenario - worker crashed while running
            can_recover = await _handle_workflow_recovery(
                run=existing_run,
                storage=storage,
                worker_id=None,
            )
            if can_recover:
                return await _recover_workflow_on_worker(
                    run=existing_run,
                    workflow_meta=workflow_meta,
                    storage=storage,
                    storage_config=storage_config,
                )
            else:
                return existing_run.run_id

        elif existing_run.status == RunStatus.SUSPENDED:
            # Workflow is suspended - this start_workflow_task is a duplicate
            # (scheduled during race condition before workflow suspended)
            # Return existing run_id - resume_workflow_task will handle it
            logger.info(
                "DUPLICATE START: Workflow already suspended, returning existing run",
                run_id=run_id,
                status=existing_run.status.value,
            )
            return existing_run.run_id

        elif existing_run.status in (
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        ):
            # Terminal status - workflow already finished
            logger.info(
                f"TERMINAL STATUS: Workflow already {existing_run.status.value}, returning existing run",
                run_id=run_id,
                status=existing_run.status.value,
            )
            return existing_run.run_id

        elif existing_run.status == RunStatus.INTERRUPTED:
            # Previous recovery failed, try again
            can_recover = await _handle_workflow_recovery(
                run=existing_run,
                storage=storage,
                worker_id=None,
            )
            if can_recover:
                return await _recover_workflow_on_worker(
                    run=existing_run,
                    workflow_meta=workflow_meta,
                    storage=storage,
                    storage_config=storage_config,
                )
            else:
                return existing_run.run_id

    # Only reach here if no existing run found
    logger.info(
        f"FRESH START: Creating new workflow run: {workflow_name}",
        run_id=run_id,
        workflow_name=workflow_name,
    )

    # Determine recovery settings
    # Priority: workflow decorator > global config > defaults based on durable mode
    recover_on_worker_loss = getattr(
        workflow_meta.func, "__workflow_recover_on_worker_loss__", None
    )
    max_recovery_attempts = getattr(workflow_meta.func, "__workflow_max_recovery_attempts__", None)
    is_durable = getattr(workflow_meta.func, "__workflow_durable__", True)

    if recover_on_worker_loss is None:
        recover_on_worker_loss = config.default_recover_on_worker_loss
        if recover_on_worker_loss is None:
            # Default: True for durable, False for transient
            recover_on_worker_loss = is_durable if is_durable is not None else True

    if max_recovery_attempts is None:
        max_recovery_attempts = config.default_max_recovery_attempts

    # Create workflow run record
    run = WorkflowRun(
        run_id=run_id,
        workflow_name=workflow_name,
        status=RunStatus.RUNNING,
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        input_args=serialize_args(*args),
        input_kwargs=serialize_kwargs(**kwargs),
        idempotency_key=idempotency_key,
        max_duration=workflow_meta.max_duration,
        context={},  # Step context (not from decorator)
        recovery_attempts=0,
        max_recovery_attempts=max_recovery_attempts,
        recover_on_worker_loss=recover_on_worker_loss,
    )

    await storage.create_run(run)

    # Record workflow started event
    start_event = create_workflow_started_event(
        run_id=run_id,
        workflow_name=workflow_name,
        args=serialize_args(*args),
        kwargs=serialize_kwargs(**kwargs),
        metadata={},  # Run-level metadata
    )

    await storage.record_event(start_event)

    # Execute workflow
    try:
        result = await execute_workflow_with_context(
            workflow_func=workflow_meta.func,
            run_id=run_id,
            workflow_name=workflow_name,
            storage=storage,
            args=args,
            kwargs=kwargs,
            runtime="celery",
            storage_config=storage_config,
        )

        # Update run status to completed
        await storage.update_run_status(
            run_id=run_id, status=RunStatus.COMPLETED, result=serialize_args(result)
        )

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.COMPLETED, storage)

        logger.info(
            f"Workflow completed successfully on worker: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
        )

        return run_id

    except CancellationError as e:
        # Workflow was cancelled
        cancelled_event = create_workflow_cancelled_event(
            run_id=run_id,
            reason=e.reason,
            cleanup_completed=True,  # If we got here, cleanup has completed
        )
        await storage.record_event(cancelled_event)
        await storage.update_run_status(run_id=run_id, status=RunStatus.CANCELLED)
        await storage.clear_cancellation_flag(run_id)

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.CANCELLED, storage)

        logger.info(
            f"Workflow cancelled on worker: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )

        return run_id

    except SuspensionSignal as e:
        # Workflow suspended (sleep, hook, or step dispatch)
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        # Record WORKFLOW_SUSPENDED event - this signals that suspension is complete
        # and resume can be safely scheduled
        step_id = e.data.get("step_id") if e.data else None
        step_name = e.data.get("step_name") if e.data else None
        sleep_id = e.data.get("sleep_id") if e.data else None
        hook_id = e.data.get("hook_id") if e.data else None
        child_id = e.data.get("child_id") if e.data else None

        suspended_event = create_workflow_suspended_event(
            run_id=run_id,
            reason=e.reason,
            step_id=step_id,
            step_name=step_name,
            sleep_id=sleep_id,
            hook_id=hook_id,
            child_id=child_id,
        )
        await storage.record_event(suspended_event)

        logger.info(
            f"Workflow suspended on worker: {e.reason}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )

        # For step dispatch suspensions, check if step already completed/failed (race condition)
        # If so, schedule resume immediately
        if step_id and e.reason.startswith("step_dispatch:"):
            events = await storage.get_events(run_id)
            step_finished = any(
                evt.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
                and evt.data.get("step_id") == step_id
                for evt in events
            )
            if step_finished:
                logger.info(
                    "Step finished before suspension completed, scheduling resume",
                    run_id=run_id,
                    step_id=step_id,
                )
                schedule_workflow_resumption(
                    run_id,
                    datetime.now(UTC),
                    storage_config=storage_config,
                    triggered_by="resume_suspension_step_race",
                )
                return run_id

        # Schedule automatic resumption if we have a resume_at time (for sleep/hook)
        resume_at = e.data.get("resume_at") if e.data else None
        if resume_at:
            schedule_workflow_resumption(
                run_id, resume_at, storage_config=storage_config, triggered_by="resume_sleep_hook"
            )
            logger.info(
                "Scheduled automatic workflow resumption",
                run_id=run_id,
                resume_at=resume_at.isoformat(),
            )

        return run_id

    except ContinueAsNewSignal as e:
        # Workflow continuing as new execution
        new_run_id = await _handle_continue_as_new_celery(
            current_run_id=run_id,
            workflow_meta=workflow_meta,
            storage=storage,
            storage_config=storage_config,
            new_args=e.workflow_args,
            new_kwargs=e.workflow_kwargs,
        )

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.CONTINUED_AS_NEW, storage)

        logger.info(
            f"Workflow continued as new on worker: {workflow_name}",
            old_run_id=run_id,
            new_run_id=new_run_id,
        )

        return run_id

    except Exception as e:
        # Workflow failed
        await storage.update_run_status(run_id=run_id, status=RunStatus.FAILED, error=str(e))

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.FAILED, storage)

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.FAILED, storage)

        logger.error(
            f"Workflow failed on worker: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            error=str(e),
            exc_info=True,
        )

        raise


@celery_app.task(
    name="pyworkflow.resume_workflow",
    base=SingletonWorkflowTask,
    queue="pyworkflow.schedules",
    unique_on=["run_id"],
)
def resume_workflow_task(
    run_id: str,
    storage_config: dict[str, Any] | None = None,
    triggered_by_hook_id: str | None = None,
) -> Any | None:
    """
    Resume a suspended workflow.

    This task is scheduled automatically when a workflow suspends (e.g., for sleep).
    It executes on Celery workers and runs the workflow directly.

    Args:
        run_id: Workflow run ID to resume
        storage_config: Storage backend configuration
        triggered_by_hook_id: Optional hook ID that triggered this resume.
                              Used to prevent spurious resumes when a workflow
                              has already moved past the triggering hook.

    Returns:
        Workflow result if completed, None if suspended again
    """
    # Ensure logging is configured in forked worker process
    from pyworkflow.celery.app import _configure_worker_logging

    _configure_worker_logging()

    logger.info(
        f"RESUME_WORKFLOW_TASK ENTRY: {run_id}",
        run_id=run_id,
        celery_task_id=resume_workflow_task.request.id,
        triggered_by_hook_id=triggered_by_hook_id,
    )

    # Get storage backend
    storage = _get_storage_backend(storage_config)

    # Resume workflow directly on worker
    result = run_async(
        _resume_workflow_on_worker(
            run_id, storage, storage_config, triggered_by_hook_id=triggered_by_hook_id
        )
    )

    if result is not None:
        logger.info(f"Workflow completed on worker: {run_id}")
    else:
        logger.info(f"Workflow suspended again on worker: {run_id}")

    return result


@celery_app.task(
    name="pyworkflow.execute_scheduled_workflow",
    base=SingletonWorkflowTask,
    queue="pyworkflow.schedules",
    # No unique_on - scheduled workflows create new runs each time, no deduplication needed
)
def execute_scheduled_workflow_task(
    schedule_id: str,
    scheduled_time: str,
    storage_config: dict[str, Any] | None = None,
) -> str | None:
    """
    Execute a workflow from a schedule.

    This task is triggered by the PyWorkflow scheduler when a schedule is due.
    It starts a new workflow run and tracks it against the schedule.

    Args:
        schedule_id: Schedule identifier
        scheduled_time: ISO format scheduled execution time
        storage_config: Storage backend configuration

    Returns:
        Workflow run ID if started, None if skipped
    """
    # Ensure logging is configured in forked worker process
    from pyworkflow.celery.app import _configure_worker_logging

    _configure_worker_logging()

    logger.info("Executing scheduled workflow", schedule_id=schedule_id)

    storage = _get_storage_backend(storage_config)

    return run_async(
        _execute_scheduled_workflow(
            schedule_id=schedule_id,
            scheduled_time=datetime.fromisoformat(scheduled_time),
            storage=storage,
            storage_config=storage_config,
        )
    )


async def _execute_scheduled_workflow(
    schedule_id: str,
    scheduled_time: datetime,
    storage: StorageBackend,
    storage_config: dict[str, Any] | None,
) -> str | None:
    """
    Execute a scheduled workflow with tracking.

    Args:
        schedule_id: Schedule identifier
        scheduled_time: When the schedule was supposed to trigger
        storage: Storage backend
        storage_config: Storage configuration for serialization

    Returns:
        Workflow run ID if started, None if skipped
    """
    # Ensure storage is connected (some backends like SQLite require this)
    if hasattr(storage, "connect"):
        await storage.connect()

    from pyworkflow.engine.events import create_schedule_triggered_event
    from pyworkflow.storage.schemas import ScheduleStatus

    # Get schedule
    schedule = await storage.get_schedule(schedule_id)
    if not schedule:
        logger.error(f"Schedule not found: {schedule_id}")
        return None

    if schedule.status != ScheduleStatus.ACTIVE:
        logger.info(f"Schedule not active: {schedule_id}")
        return None

    # Get workflow
    workflow_meta = get_workflow(schedule.workflow_name)
    if not workflow_meta:
        logger.error(f"Workflow not found: {schedule.workflow_name}")
        schedule.failed_runs += 1
        schedule.updated_at = datetime.now(UTC)
        await storage.update_schedule(schedule)
        return None

    # Deserialize arguments
    args = deserialize_args(schedule.args)
    kwargs = deserialize_kwargs(schedule.kwargs)

    # Generate run_id
    run_id = f"sched_{schedule_id[:8]}_{uuid.uuid4().hex[:8]}"

    # Add to running runs
    await storage.add_running_run(schedule_id, run_id)

    # Update schedule stats
    schedule.total_runs += 1
    schedule.last_run_at = datetime.now(UTC)
    schedule.last_run_id = run_id
    await storage.update_schedule(schedule)

    try:
        # Serialize args for Celery task
        args_json = serialize_args(*args)
        kwargs_json = serialize_kwargs(**kwargs)

        # Start the workflow via Celery
        # Note: start_workflow_task will create the run record
        start_workflow_task.delay(
            workflow_name=schedule.workflow_name,
            args_json=args_json,
            kwargs_json=kwargs_json,
            run_id=run_id,
            storage_config=storage_config,
            # Note: context data is passed through for scheduled workflows to include schedule info
        )

        # Record trigger event - use schedule_id as run_id since workflow run may not exist yet
        trigger_event = create_schedule_triggered_event(
            run_id=schedule_id,  # Use schedule_id for event association
            schedule_id=schedule_id,
            scheduled_time=scheduled_time,
            actual_time=datetime.now(UTC),
            workflow_run_id=run_id,
        )
        await storage.record_event(trigger_event)

        logger.info(
            f"Started scheduled workflow: {schedule.workflow_name}",
            schedule_id=schedule_id,
            run_id=run_id,
        )

        return run_id

    except Exception as e:
        logger.error(f"Failed to start scheduled workflow: {e}")
        await storage.remove_running_run(schedule_id, run_id)
        schedule.failed_runs += 1
        schedule.updated_at = datetime.now(UTC)
        await storage.update_schedule(schedule)
        raise


async def _complete_pending_sleeps(
    run_id: str,
    events: list[Any],
    storage: StorageBackend,
) -> list[Any]:
    """
    Record SLEEP_COMPLETED events for any pending sleeps.

    When resuming a workflow, we need to mark sleeps as completed
    so the replay logic knows to skip them.

    Args:
        run_id: Workflow run ID
        events: Current event list
        storage: Storage backend

    Returns:
        Updated event list with SLEEP_COMPLETED events appended
    """
    from pyworkflow.engine.events import EventType, create_sleep_completed_event

    # Find pending sleeps (SLEEP_STARTED without SLEEP_COMPLETED)
    started_sleeps = set()
    completed_sleeps = set()

    for event in events:
        if event.type == EventType.SLEEP_STARTED:
            started_sleeps.add(event.data.get("sleep_id"))
        elif event.type == EventType.SLEEP_COMPLETED:
            completed_sleeps.add(event.data.get("sleep_id"))

    pending_sleeps = started_sleeps - completed_sleeps

    if not pending_sleeps:
        return events

    # Record SLEEP_COMPLETED for each pending sleep
    updated_events = list(events)
    for sleep_id in pending_sleeps:
        complete_event = create_sleep_completed_event(
            run_id=run_id,
            sleep_id=sleep_id,
        )
        await storage.record_event(complete_event)
        updated_events.append(complete_event)
        logger.debug(f"Recorded SLEEP_COMPLETED for {sleep_id}", run_id=run_id)

    return updated_events


def _is_hook_still_relevant(hook_id: str, events: list[Any]) -> bool:
    """
    Check if a hook is still relevant for resuming the workflow.

    A hook is "still relevant" if there are no newer hooks created after
    this hook was received. This prevents spurious resumes when:
    1. resume_hook() is called multiple times for the same hook
    2. The workflow moved past the first resume and created a new hook
    3. The duplicate resume task runs but the workflow is now waiting on a different hook

    Args:
        hook_id: The hook ID that triggered the resume
        events: List of workflow events

    Returns:
        True if the hook is still relevant, False if workflow has moved past it
    """
    from pyworkflow.engine.events import EventType

    # Sort events by sequence to process in order
    sorted_events = sorted(events, key=lambda e: e.sequence or 0)

    # Find the sequence number of HOOK_RECEIVED for this hook
    hook_received_sequence = None
    for event in sorted_events:
        if event.type == EventType.HOOK_RECEIVED and event.data.get("hook_id") == hook_id:
            hook_received_sequence = event.sequence
            break

    if hook_received_sequence is None:
        # Hook was never received - shouldn't happen, but allow resume
        logger.warning(
            f"Hook {hook_id} was not found in HOOK_RECEIVED events, allowing resume",
            hook_id=hook_id,
        )
        return True

    # Check if there's a HOOK_CREATED event after this hook was received
    # (indicating the workflow has moved past this hook and created a new one)
    for event in sorted_events:
        if event.type == EventType.HOOK_CREATED:
            event_sequence = event.sequence or 0
            if event_sequence > hook_received_sequence:
                # There's a newer hook - this resume is stale
                newer_hook_id = event.data.get("hook_id")
                logger.debug(
                    f"Found newer hook {newer_hook_id} (seq {event_sequence}) "
                    f"after triggered hook {hook_id} (received at seq {hook_received_sequence})",
                    hook_id=hook_id,
                    newer_hook_id=newer_hook_id,
                )
                return False

    # No newer hooks created - this resume is still relevant
    return True


async def _resume_workflow_on_worker(
    run_id: str,
    storage: StorageBackend,
    storage_config: dict[str, Any] | None = None,
    triggered_by_hook_id: str | None = None,
) -> Any | None:
    """
    Internal function to resume workflow on Celery worker.

    This mirrors the logic from testing.py but runs on workers.

    Args:
        run_id: Workflow run ID to resume
        storage: Storage backend
        storage_config: Storage configuration for task dispatch
        triggered_by_hook_id: Optional hook ID that triggered this resume.
                              If provided, we verify the hook is still relevant
                              before resuming to prevent spurious resumes.
    """
    from pyworkflow.core.exceptions import WorkflowNotFoundError

    # Ensure storage is connected (some backends like SQLite require this)
    if hasattr(storage, "connect"):
        await storage.connect()

    # Load workflow run
    run = await storage.get_run(run_id)
    if not run:
        raise WorkflowNotFoundError(run_id)

    # Check if workflow was cancelled while suspended
    if run.status == RunStatus.CANCELLED:
        logger.info(
            "Workflow was cancelled while suspended, skipping resume",
            run_id=run_id,
            workflow_name=run.workflow_name,
        )
        return None

    # Prevent duplicate resume execution
    # Multiple resume tasks can be scheduled for the same workflow (e.g., race
    # condition between step completion and suspension handler). Only proceed
    # if the workflow is actually SUSPENDED. If status is RUNNING, another
    # resume task got there first.
    if run.status != RunStatus.SUSPENDED:
        logger.info(
            f"Workflow status is {run.status.value}, not SUSPENDED - skipping duplicate resume",
            run_id=run_id,
            workflow_name=run.workflow_name,
        )
        return None

    # If this resume was triggered by a specific hook, verify the hook is still relevant.
    # A hook is "stale" if the workflow has already moved past it (created a newer hook).
    # This prevents spurious resumes from duplicate resume_hook() calls.
    if triggered_by_hook_id:
        events = await storage.get_events(run_id)
        hook_still_relevant = _is_hook_still_relevant(triggered_by_hook_id, events)
        if not hook_still_relevant:
            logger.info(
                f"Hook {triggered_by_hook_id} is no longer relevant (workflow moved past it), "
                "skipping spurious resume",
                run_id=run_id,
                workflow_name=run.workflow_name,
                triggered_by_hook_id=triggered_by_hook_id,
            )
            return None

    # Check for cancellation flag
    cancellation_requested = await storage.check_cancellation_flag(run_id)

    logger.info(
        f"Resuming workflow execution on worker: {run.workflow_name}",
        run_id=run_id,
        workflow_name=run.workflow_name,
        current_status=run.status.value,
        cancellation_requested=cancellation_requested,
    )

    # Get workflow function
    workflow_meta = get_workflow(run.workflow_name)
    if not workflow_meta:
        raise ValueError(f"Workflow '{run.workflow_name}' not registered")

    # Load event log
    events = await storage.get_events(run_id)

    # Complete any pending sleeps (mark them as done before resuming)
    events = await _complete_pending_sleeps(run_id, events, storage)

    # Deserialize arguments
    args = deserialize_args(run.input_args)
    kwargs = deserialize_kwargs(run.input_kwargs)

    # Update status to running
    await storage.update_run_status(run_id=run_id, status=RunStatus.RUNNING)

    # Execute workflow with event replay
    try:
        result = await execute_workflow_with_context(
            workflow_func=workflow_meta.func,
            run_id=run_id,
            workflow_name=run.workflow_name,
            storage=storage,
            args=args,
            kwargs=kwargs,
            event_log=events,
            cancellation_requested=cancellation_requested,
            runtime="celery",
            storage_config=storage_config,
        )

        # Update run status to completed
        await storage.update_run_status(
            run_id=run_id, status=RunStatus.COMPLETED, result=serialize_args(result)
        )

        # Clear cancellation flag if any
        await storage.clear_cancellation_flag(run_id)

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.COMPLETED, storage)

        # Notify parent if this is a child workflow
        await _notify_parent_of_child_completion(
            run=run,
            storage=storage,
            storage_config=storage_config,
            status=RunStatus.COMPLETED,
            result=serialize_args(result),
        )

        logger.info(
            f"Workflow resumed and completed on worker: {run.workflow_name}",
            run_id=run_id,
            workflow_name=run.workflow_name,
        )

        return result

    except CancellationError as e:
        # Workflow was cancelled
        cancelled_event = create_workflow_cancelled_event(
            run_id=run_id,
            reason=e.reason,
            cleanup_completed=True,
        )
        await storage.record_event(cancelled_event)
        await storage.update_run_status(run_id=run_id, status=RunStatus.CANCELLED)
        await storage.clear_cancellation_flag(run_id)

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.CANCELLED, storage)

        # Notify parent if this is a child workflow
        await _notify_parent_of_child_completion(
            run=run,
            storage=storage,
            storage_config=storage_config,
            status=RunStatus.CANCELLED,
            error=e.reason,
        )

        logger.info(
            f"Workflow cancelled on resume on worker: {run.workflow_name}",
            run_id=run_id,
            workflow_name=run.workflow_name,
            reason=e.reason,
        )

        return None

    except SuspensionSignal as e:
        # Workflow suspended again (during resume)
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        # Record WORKFLOW_SUSPENDED event
        step_id = e.data.get("step_id") if e.data else None
        step_name = e.data.get("step_name") if e.data else None
        sleep_id = e.data.get("sleep_id") if e.data else None
        hook_id = e.data.get("hook_id") if e.data else None
        child_id = e.data.get("child_id") if e.data else None

        suspended_event = create_workflow_suspended_event(
            run_id=run_id,
            reason=e.reason,
            step_id=step_id,
            step_name=step_name,
            sleep_id=sleep_id,
            hook_id=hook_id,
            child_id=child_id,
        )
        await storage.record_event(suspended_event)

        logger.info(
            f"Workflow suspended again on worker: {e.reason}",
            run_id=run_id,
            workflow_name=run.workflow_name,
            reason=e.reason,
        )

        # For step dispatch suspensions, check if step already completed/failed
        if step_id and e.reason.startswith("step_dispatch:"):
            events = await storage.get_events(run_id)
            step_finished = any(
                evt.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
                and evt.data.get("step_id") == step_id
                for evt in events
            )
            if step_finished:
                logger.info(
                    "Step finished before resume suspension completed, scheduling resume",
                    run_id=run_id,
                    step_id=step_id,
                )
                schedule_workflow_resumption(
                    run_id,
                    datetime.now(UTC),
                    storage_config=storage_config,
                    triggered_by="start_suspension_step_race",
                )
                return None

        # Schedule automatic resumption if we have a resume_at time
        resume_at = e.data.get("resume_at") if e.data else None
        if resume_at:
            schedule_workflow_resumption(
                run_id, resume_at, storage_config=storage_config, triggered_by="start_sleep_hook"
            )
            logger.info(
                "Scheduled automatic workflow resumption",
                run_id=run_id,
                resume_at=resume_at.isoformat(),
            )

        return None

    except ContinueAsNewSignal as e:
        # Workflow continuing as new execution
        workflow_meta = get_workflow(run.workflow_name)
        if not workflow_meta:
            raise ValueError(f"Workflow {run.workflow_name} not registered")

        new_run_id = await _handle_continue_as_new_celery(
            current_run_id=run_id,
            workflow_meta=workflow_meta,
            storage=storage,
            storage_config=storage_config,
            new_args=e.workflow_args,
            new_kwargs=e.workflow_kwargs,
            parent_run_id=run.parent_run_id,
        )

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.CONTINUED_AS_NEW, storage)

        logger.info(
            f"Workflow continued as new on resume: {run.workflow_name}",
            old_run_id=run_id,
            new_run_id=new_run_id,
        )

        return None

    except Exception as e:
        # Workflow failed
        error_msg = str(e)
        error_type = type(e).__name__
        await storage.update_run_status(run_id=run_id, status=RunStatus.FAILED, error=error_msg)

        # Cancel all running children (TERMINATE policy)
        await _handle_parent_completion(run_id, RunStatus.FAILED, storage)

        # Notify parent if this is a child workflow
        await _notify_parent_of_child_completion(
            run=run,
            storage=storage,
            storage_config=storage_config,
            status=RunStatus.FAILED,
            error=error_msg,
            error_type=error_type,
        )

        logger.error(
            f"Workflow failed on resume on worker: {run.workflow_name}",
            run_id=run_id,
            workflow_name=run.workflow_name,
            error=error_msg,
            exc_info=True,
        )

        raise


def _get_storage_backend(config: dict[str, Any] | None = None) -> StorageBackend:
    """
    Get storage backend from configuration.

    This is an alias for config_to_storage for backward compatibility.
    """
    from pyworkflow.storage.config import config_to_storage

    storage = config_to_storage(config)
    return storage


def schedule_workflow_resumption(
    run_id: str,
    resume_at: datetime,
    storage_config: dict[str, Any] | None = None,
    triggered_by: str = "unknown",
) -> None:
    """
    Schedule automatic workflow resumption after sleep.

    Args:
        run_id: Workflow run ID
        resume_at: When to resume the workflow
        storage_config: Storage backend configuration to pass to the resume task
        triggered_by: What triggered this resume scheduling (for debugging)
    """
    from datetime import UTC

    # Calculate delay in seconds
    now = datetime.now(UTC)
    delay_seconds = max(0, int((resume_at - now).total_seconds()))

    logger.info(
        f"SCHEDULE_RESUME: {triggered_by}",
        run_id=run_id,
        resume_at=resume_at.isoformat(),
        delay_seconds=delay_seconds,
        triggered_by=triggered_by,
    )

    # Schedule the resume task
    resume_workflow_task.apply_async(
        args=[run_id],
        kwargs={"storage_config": storage_config},
        countdown=delay_seconds,
    )


async def _handle_parent_completion(
    run_id: str,
    status: RunStatus,
    storage: StorageBackend,
) -> None:
    """
    Handle parent workflow completion by cancelling all running children.

    When a parent workflow reaches a terminal state (COMPLETED, FAILED, CANCELLED),
    all running child workflows are automatically cancelled. This implements the
    TERMINATE parent close policy.

    Args:
        run_id: Parent workflow run ID
        status: Terminal status of the parent workflow
        storage: Storage backend
    """
    from pyworkflow.engine.executor import cancel_workflow

    # Get all non-terminal children
    children = await storage.get_children(run_id)
    non_terminal_statuses = {
        RunStatus.PENDING,
        RunStatus.RUNNING,
        RunStatus.SUSPENDED,
        RunStatus.INTERRUPTED,
    }

    running_children = [c for c in children if c.status in non_terminal_statuses]

    if not running_children:
        return

    logger.info(
        f"Cancelling {len(running_children)} child workflow(s) due to parent {status.value}",
        parent_run_id=run_id,
        parent_status=status.value,
        child_count=len(running_children),
    )

    # Cancel each running child
    for child in running_children:
        try:
            reason = f"Parent workflow {run_id} {status.value}"

            # Cancel the child workflow
            await cancel_workflow(
                run_id=child.run_id,
                reason=reason,
                storage=storage,
            )

            # Find the child_id from parent's events
            events = await storage.get_events(run_id)
            child_id = None
            for event in events:
                if (
                    event.type == EventType.CHILD_WORKFLOW_STARTED
                    and event.data.get("child_run_id") == child.run_id
                ):
                    child_id = event.data.get("child_id")
                    break

            # Record cancellation event in parent's log
            if child_id:
                cancel_event = create_child_workflow_cancelled_event(
                    run_id=run_id,
                    child_id=child_id,
                    child_run_id=child.run_id,
                    reason=reason,
                )
                await storage.record_event(cancel_event)

            logger.info(
                f"Cancelled child workflow: {child.workflow_name}",
                parent_run_id=run_id,
                child_run_id=child.run_id,
                child_workflow_name=child.workflow_name,
            )

        except Exception as e:
            # Log error but don't fail parent completion
            logger.error(
                f"Failed to cancel child workflow: {child.workflow_name}",
                parent_run_id=run_id,
                child_run_id=child.run_id,
                error=str(e),
            )


async def _handle_continue_as_new_celery(
    current_run_id: str,
    workflow_meta: WorkflowMetadata,
    storage: StorageBackend,
    storage_config: dict[str, Any] | None,
    new_args: tuple,
    new_kwargs: dict,
    parent_run_id: str | None = None,
) -> str:
    """
    Handle continue-as-new in Celery context.

    This function:
    1. Generates new run_id
    2. Records WORKFLOW_CONTINUED_AS_NEW event in current run
    3. Updates current run status to CONTINUED_AS_NEW
    4. Updates current run's continued_to_run_id
    5. Creates new WorkflowRun with continued_from_run_id
    6. Schedules new workflow execution via Celery

    Args:
        current_run_id: The run ID of the current workflow
        workflow_meta: Workflow metadata
        storage: Storage backend
        storage_config: Storage configuration for serialization
        new_args: Arguments for the new workflow
        new_kwargs: Keyword arguments for the new workflow
        parent_run_id: Parent run ID if this is a child workflow

    Returns:
        New run ID
    """
    # Generate new run_id
    new_run_id = f"run_{uuid.uuid4().hex[:16]}"

    # Serialize arguments
    args_json = serialize_args(*new_args)
    kwargs_json = serialize_kwargs(**new_kwargs)

    # Record continuation event in current run's log
    continuation_event = create_workflow_continued_as_new_event(
        run_id=current_run_id,
        new_run_id=new_run_id,
        args=args_json,
        kwargs=kwargs_json,
    )
    await storage.record_event(continuation_event)

    # Update current run status and link to new run
    await storage.update_run_status(
        run_id=current_run_id,
        status=RunStatus.CONTINUED_AS_NEW,
    )
    await storage.update_run_continuation(
        run_id=current_run_id,
        continued_to_run_id=new_run_id,
    )

    # Get current run to copy metadata
    current_run = await storage.get_run(current_run_id)
    nesting_depth = current_run.nesting_depth if current_run else 0

    # Create new workflow run linked to current
    new_run = WorkflowRun(
        run_id=new_run_id,
        workflow_name=workflow_meta.name,
        status=RunStatus.PENDING,
        created_at=datetime.now(UTC),
        input_args=args_json,
        input_kwargs=kwargs_json,
        continued_from_run_id=current_run_id,
        nesting_depth=nesting_depth,
        parent_run_id=parent_run_id,
    )
    await storage.create_run(new_run)

    # Schedule new workflow execution via Celery
    start_workflow_task.delay(
        workflow_name=workflow_meta.name,
        args_json=args_json,
        kwargs_json=kwargs_json,
        run_id=new_run_id,
        storage_config=storage_config,
    )

    return new_run_id
