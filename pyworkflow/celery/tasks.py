"""
Celery tasks for distributed workflow and step execution.

These tasks enable:
- Distributed step execution across workers
- Automatic retry with exponential backoff
- Scheduled sleep resumption
- Workflow orchestration
- Fault tolerance with automatic recovery on worker failures
"""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyworkflow.context.step_context import StepContext

from celery import Task
from celery.exceptions import WorkerLostError
from loguru import logger

from pyworkflow.celery.app import celery_app
from pyworkflow.core.exceptions import (
    CancellationError,
    ContinueAsNewSignal,
    FatalError,
    RetryableError,
    SuspensionSignal,
)
from pyworkflow.core.registry import WorkflowMetadata, get_workflow
from pyworkflow.core.workflow import execute_workflow_with_context
from pyworkflow.engine.events import (
    EventType,
    create_child_workflow_cancelled_event,
    create_workflow_cancelled_event,
    create_workflow_continued_as_new_event,
    create_workflow_interrupted_event,
    create_workflow_started_event,
)
from pyworkflow.serialization.decoder import deserialize_args, deserialize_kwargs
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


class WorkflowTask(Task):
    """Base task class for workflow execution with custom error handling."""

    autoretry_for = (RetryableError,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """
        Handle task failure.

        Detects worker loss and handles recovery appropriately:
        - WorkerLostError: Infrastructure failure, may trigger recovery
        - Other exceptions: Application failure
        """
        is_worker_loss = isinstance(exc, WorkerLostError)

        if is_worker_loss:
            logger.warning(
                f"Task {self.name} interrupted due to worker loss",
                task_id=task_id,
                error=str(exc),
            )
            # Note: Recovery is handled when the task is requeued and picked up
            # by another worker. See _handle_workflow_recovery() for logic.
        else:
            logger.error(
                f"Task {self.name} failed",
                task_id=task_id,
                error=str(exc),
                traceback=einfo.traceback if einfo else None,
            )

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Handle task retry."""
        logger.warning(
            f"Task {self.name} retrying",
            task_id=task_id,
            error=str(exc),
            retry_count=self.request.retries,
        )


@celery_app.task(
    name="pyworkflow.execute_step",
    base=WorkflowTask,
    bind=True,
    queue="pyworkflow.steps",
)
def execute_step_task(
    self: WorkflowTask,
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
        FatalError: For non-retriable errors
        RetryableError: For retriable errors (triggers automatic retry)
    """
    from pyworkflow.core.registry import _registry

    logger.info(
        f"Executing dispatched step: {step_name}",
        run_id=run_id,
        step_id=step_id,
        attempt=self.request.retries + 1,
    )

    # Get step metadata
    step_meta = _registry.get_step(step_name)
    if not step_meta:
        # Record failure and resume workflow
        asyncio.run(
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

    # Deserialize arguments
    args = deserialize_args(args_json)
    kwargs = deserialize_kwargs(kwargs_json)

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
            result = asyncio.run(step_func(*args, **kwargs))
        else:
            result = step_func(*args, **kwargs)

        logger.info(
            f"Step completed: {step_name}",
            run_id=run_id,
            step_id=step_id,
        )

        # Record STEP_COMPLETED event and trigger workflow resumption
        asyncio.run(
            _record_step_completion_and_resume(
                storage_config=storage_config,
                run_id=run_id,
                step_id=step_id,
                step_name=step_name,
                result=result,
            )
        )

        return result

    except FatalError as e:
        logger.error(f"Step failed (fatal): {step_name}", run_id=run_id, step_id=step_id)
        # Record failure and resume workflow (workflow will fail on replay)
        asyncio.run(
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
            logger.warning(
                f"Step failed (retriable): {step_name}, retrying...",
                run_id=run_id,
                step_id=step_id,
                retry_after=e.retry_after,
                attempt=self.request.retries + 1,
                max_retries=max_retries,
            )
            # Let Celery handle the retry - don't resume workflow yet
            raise self.retry(exc=e, countdown=e.get_retry_delay_seconds() or 60)
        else:
            # Max retries exhausted - record failure and resume workflow
            logger.error(
                f"Step failed after {max_retries + 1} attempts: {step_name}",
                run_id=run_id,
                step_id=step_id,
            )
            asyncio.run(
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
            raise

    except Exception as e:
        # Check if we have retries left
        if self.request.retries < max_retries:
            logger.warning(
                f"Step failed (unexpected): {step_name}, retrying...",
                run_id=run_id,
                step_id=step_id,
                error=str(e),
                attempt=self.request.retries + 1,
            )
            # Treat unexpected errors as retriable
            raise self.retry(exc=RetryableError(str(e)), countdown=60)
        else:
            # Max retries exhausted
            logger.error(
                f"Step failed after {max_retries + 1} attempts: {step_name}",
                run_id=run_id,
                step_id=step_id,
                error=str(e),
                exc_info=True,
            )
            asyncio.run(
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
    Record STEP_COMPLETED event and trigger workflow resumption.

    Called by execute_step_task after successful step execution.
    """
    from pyworkflow.engine.events import create_step_completed_event
    from pyworkflow.serialization.encoder import serialize

    # Get storage backend
    storage = _get_storage_backend(storage_config)

    # Ensure storage is connected
    if hasattr(storage, "connect"):
        await storage.connect()

    # Record STEP_COMPLETED event
    completion_event = create_step_completed_event(
        run_id=run_id,
        step_id=step_id,
        result=serialize(result),
        step_name=step_name,
    )
    await storage.record_event(completion_event)

    # Schedule workflow resumption immediately
    schedule_workflow_resumption(run_id, datetime.now(UTC), storage_config)

    logger.info(
        "Step completed and workflow resumption scheduled",
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
    Record STEP_FAILED event and trigger workflow resumption.

    Called by execute_step_task after step failure (when retries are exhausted).
    The workflow will fail when it replays and sees the failure event.
    """
    from pyworkflow.engine.events import create_step_failed_event

    # Get storage backend
    storage = _get_storage_backend(storage_config)

    # Ensure storage is connected
    if hasattr(storage, "connect"):
        await storage.connect()

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

    # Schedule workflow resumption - workflow will fail on replay
    schedule_workflow_resumption(run_id, datetime.now(UTC), storage_config)

    logger.info(
        "Step failed and workflow resumption scheduled",
        run_id=run_id,
        step_id=step_id,
        step_name=step_name,
        error=error,
    )


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
    queue="pyworkflow.workflows",
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
    logger.info(f"Starting workflow on worker: {workflow_name}", run_id=run_id)

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
    result_run_id = asyncio.run(
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
    queue="pyworkflow.workflows",
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
    asyncio.run(
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
        # Child workflow suspended (e.g., sleep, hook)
        # Update status and don't notify parent yet - handled on child resumption
        await storage.update_run_status(child_run_id, RunStatus.SUSPENDED)
        logger.debug(
            f"Child workflow suspended: {workflow_name}",
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
        )

        # Schedule automatic resumption if we have a resume_at time
        resume_at = e.data.get("resume_at") if e.data else None
        if resume_at:
            schedule_workflow_resumption(child_run_id, resume_at, storage_config)

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
        schedule_workflow_resumption(parent_run_id, datetime.now(UTC), storage_config)


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
        # Workflow suspended again
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        logger.info(
            f"Recovered workflow suspended: {e.reason}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )

        # Schedule automatic resumption if we have a resume_at time
        resume_at = e.data.get("resume_at") if e.data else None
        if resume_at:
            schedule_workflow_resumption(run_id, resume_at, storage_config=storage_config)
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

    # Check idempotency key
    if idempotency_key:
        existing_run = await storage.get_run_by_idempotency_key(idempotency_key)
        if existing_run:
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

    # Check if run already exists (recovery scenario without idempotency key)
    existing_run = await storage.get_run(run_id)
    if existing_run and existing_run.status == RunStatus.RUNNING:
        # This is a recovery scenario
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

    logger.info(
        f"Starting workflow execution on worker: {workflow_name}",
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
        # Workflow suspended (sleep or hook)
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        logger.info(
            f"Workflow suspended on worker: {e.reason}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )

        # Schedule automatic resumption if we have a resume_at time
        resume_at = e.data.get("resume_at") if e.data else None
        if resume_at:
            schedule_workflow_resumption(run_id, resume_at, storage_config=storage_config)
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
    queue="pyworkflow.schedules",
)
def resume_workflow_task(
    run_id: str,
    storage_config: dict[str, Any] | None = None,
) -> Any | None:
    """
    Resume a suspended workflow.

    This task is scheduled automatically when a workflow suspends (e.g., for sleep).
    It executes on Celery workers and runs the workflow directly.

    Args:
        run_id: Workflow run ID to resume
        storage_config: Storage backend configuration

    Returns:
        Workflow result if completed, None if suspended again
    """
    logger.info(f"Resuming workflow on worker: {run_id}")

    # Get storage backend
    storage = _get_storage_backend(storage_config)

    # Resume workflow directly on worker
    result = asyncio.run(_resume_workflow_on_worker(run_id, storage, storage_config))

    if result is not None:
        logger.info(f"Workflow completed on worker: {run_id}")
    else:
        logger.info(f"Workflow suspended again on worker: {run_id}")

    return result


@celery_app.task(
    name="pyworkflow.execute_scheduled_workflow",
    queue="pyworkflow.schedules",
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
    logger.info("Executing scheduled workflow", schedule_id=schedule_id)

    storage = _get_storage_backend(storage_config)

    return asyncio.run(
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


async def _resume_workflow_on_worker(
    run_id: str,
    storage: StorageBackend,
    storage_config: dict[str, Any] | None = None,
) -> Any | None:
    """
    Internal function to resume workflow on Celery worker.

    This mirrors the logic from testing.py but runs on workers.
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
        # Workflow suspended again
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        logger.info(
            f"Workflow suspended again on worker: {e.reason}",
            run_id=run_id,
            workflow_name=run.workflow_name,
            reason=e.reason,
        )

        # Schedule automatic resumption if we have a resume_at time
        resume_at = e.data.get("resume_at") if e.data else None
        if resume_at:
            schedule_workflow_resumption(run_id, resume_at, storage_config=storage_config)
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

    return config_to_storage(config)


def schedule_workflow_resumption(
    run_id: str,
    resume_at: datetime,
    storage_config: dict[str, Any] | None = None,
) -> None:
    """
    Schedule automatic workflow resumption after sleep.

    Args:
        run_id: Workflow run ID
        resume_at: When to resume the workflow
        storage_config: Storage backend configuration to pass to the resume task
    """
    from datetime import UTC

    # Calculate delay in seconds
    now = datetime.now(UTC)
    delay_seconds = max(0, int((resume_at - now).total_seconds()))

    logger.info(
        "Scheduling workflow resumption",
        run_id=run_id,
        resume_at=resume_at.isoformat(),
        delay_seconds=delay_seconds,
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
