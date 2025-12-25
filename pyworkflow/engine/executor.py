"""
Workflow execution engine.

The executor is responsible for:
- Starting new workflow runs
- Resuming existing runs
- Managing workflow lifecycle
- Coordinating with storage backend and runtimes

Supports multiple runtimes (local, celery) and durability modes (durable, transient).
"""

import uuid
from collections.abc import Callable
from typing import Any

from loguru import logger

from pyworkflow.core.exceptions import (
    ContinueAsNewSignal,
    SuspensionSignal,
    WorkflowAlreadyRunningError,
    WorkflowNotFoundError,
)
from pyworkflow.core.registry import get_workflow_by_func
from pyworkflow.core.workflow import execute_workflow_with_context
from pyworkflow.engine.events import (
    create_cancellation_requested_event,
    create_workflow_cancelled_event,
    create_workflow_continued_as_new_event,
)
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


class ConfigurationError(Exception):
    """Configuration error for PyWorkflow."""

    pass


async def start(
    workflow_func: Callable,
    *args: Any,
    runtime: str | None = None,
    durable: bool | None = None,
    storage: StorageBackend | None = None,
    idempotency_key: str | None = None,
    **kwargs: Any,
) -> str:
    """
    Start a new workflow execution.

    The runtime and durability mode can be specified per-call, or will use
    the configured defaults.

    Args:
        workflow_func: Workflow function decorated with @workflow
        *args: Positional arguments for workflow
        runtime: Runtime to use ("local", "celery", etc.) or None for default
        durable: Whether workflow is durable (None = use workflow/config default)
        storage: Storage backend instance (None = use configured storage)
        idempotency_key: Optional key for idempotent execution
        **kwargs: Keyword arguments for workflow

    Returns:
        run_id: Unique identifier for this workflow run

    Examples:
        # Basic usage (uses configured defaults)
        run_id = await start(my_workflow, 42)

        # Transient workflow (no persistence)
        run_id = await start(my_workflow, 42, durable=False)

        # Durable workflow with storage
        run_id = await start(
            my_workflow, 42,
            durable=True,
            storage=InMemoryStorageBackend()
        )

        # Explicit local runtime
        run_id = await start(my_workflow, 42, runtime="local")

        # With idempotency key
        run_id = await start(
            my_workflow, 42,
            idempotency_key="unique-operation-id"
        )
    """
    from pyworkflow.config import get_config
    from pyworkflow.runtime import get_runtime, validate_runtime_durable

    config = get_config()

    # Get workflow metadata
    workflow_meta = get_workflow_by_func(workflow_func)
    if not workflow_meta:
        raise ValueError(
            f"Function {workflow_func.__name__} is not registered as a workflow. "
            f"Did you forget the @workflow decorator?"
        )

    workflow_name = workflow_meta.name

    # Resolve runtime
    runtime_name = runtime or config.default_runtime
    runtime_instance = get_runtime(runtime_name)

    # Resolve durable flag (priority: call arg > decorator > config default)
    workflow_durable = getattr(workflow_func, "__workflow_durable__", None)
    effective_durable = (
        durable
        if durable is not None
        else workflow_durable
        if workflow_durable is not None
        else config.default_durable
    )

    # Validate runtime + durable combination
    validate_runtime_durable(runtime_instance, effective_durable)

    # Resolve storage
    effective_storage = storage or config.storage
    if effective_durable and effective_storage is None:
        raise ConfigurationError(
            "Durable workflows require storage. Either:\n"
            "  1. Pass storage=... to start()\n"
            "  2. Configure globally via pyworkflow.configure(storage=...)\n"
            "  3. Use durable=False for transient workflows"
        )

    # Check idempotency key (only for durable workflows with storage)
    if idempotency_key and effective_durable and effective_storage:
        existing_run = await effective_storage.get_run_by_idempotency_key(idempotency_key)
        if existing_run:
            if existing_run.status == RunStatus.RUNNING:
                raise WorkflowAlreadyRunningError(existing_run.run_id)
            logger.info(
                f"Workflow with idempotency key '{idempotency_key}' already exists",
                run_id=existing_run.run_id,
                status=existing_run.status.value,
            )
            return existing_run.run_id

    # Generate run_id
    run_id = f"run_{uuid.uuid4().hex[:16]}"

    logger.info(
        f"Starting workflow: {workflow_name}",
        run_id=run_id,
        workflow_name=workflow_name,
        runtime=runtime_name,
        durable=effective_durable,
    )

    # Execute via runtime
    return await runtime_instance.start_workflow(
        workflow_func=workflow_meta.func,
        args=args,
        kwargs=kwargs,
        run_id=run_id,
        workflow_name=workflow_name,
        storage=effective_storage,
        durable=effective_durable,
        idempotency_key=idempotency_key,
        max_duration=workflow_meta.max_duration,
        metadata={},  # Run-level metadata
    )


async def resume(
    run_id: str,
    runtime: str | None = None,
    storage: StorageBackend | None = None,
) -> Any:
    """
    Resume a suspended workflow.

    Args:
        run_id: Workflow run identifier
        runtime: Runtime to use (None = use configured default)
        storage: Storage backend (None = use configured storage)

    Returns:
        Workflow result (if completed) or None (if suspended again)

    Examples:
        # Resume with configured defaults
        result = await resume("run_abc123")

        # Resume with explicit storage
        result = await resume("run_abc123", storage=my_storage)
    """
    from pyworkflow.config import get_config
    from pyworkflow.runtime import get_runtime

    config = get_config()

    # Resolve runtime and storage
    runtime_name = runtime or config.default_runtime
    runtime_instance = get_runtime(runtime_name)
    effective_storage = storage or config.storage

    if effective_storage is None:
        raise ConfigurationError(
            "Cannot resume workflow without storage. "
            "Configure storage via pyworkflow.configure(storage=...) "
            "or pass storage=... to resume()"
        )

    logger.info(
        f"Resuming workflow: {run_id}",
        run_id=run_id,
        runtime=runtime_name,
    )

    return await runtime_instance.resume_workflow(
        run_id=run_id,
        storage=effective_storage,
    )


# Internal functions for Celery tasks
# These execute workflows locally on workers


async def _execute_workflow_local(
    workflow_func: Callable,
    run_id: str,
    workflow_name: str,
    storage: StorageBackend,
    args: tuple,
    kwargs: dict,
    event_log: list | None = None,
) -> Any:
    """
    Execute workflow locally (used by Celery tasks).

    This is an internal function called by Celery workers to execute
    workflows. It handles the actual workflow execution with context.

    Args:
        workflow_func: Workflow function to execute
        run_id: Workflow run ID
        workflow_name: Workflow name
        storage: Storage backend
        args: Workflow arguments
        kwargs: Workflow keyword arguments
        event_log: Optional event log for replay

    Returns:
        Workflow result or None if suspended

    Raises:
        Exception: On workflow failure
    """
    try:
        result = await execute_workflow_with_context(
            workflow_func=workflow_func,
            run_id=run_id,
            workflow_name=workflow_name,
            storage=storage,
            args=args,
            kwargs=kwargs,
            event_log=event_log,
            durable=True,  # Celery tasks are always durable
        )

        # Update run status to completed
        await storage.update_run_status(
            run_id=run_id, status=RunStatus.COMPLETED, result=serialize_args(result)
        )

        logger.info(
            f"Workflow completed successfully: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
        )

        return result

    except SuspensionSignal as e:
        # Workflow suspended (sleep or hook)
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        logger.info(
            f"Workflow suspended: {e.reason}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )

        return None

    except ContinueAsNewSignal as e:
        # Workflow continuing as new execution
        new_run_id = await _handle_continue_as_new(
            current_run_id=run_id,
            workflow_func=workflow_func,
            workflow_name=workflow_name,
            storage=storage,
            new_args=e.workflow_args,
            new_kwargs=e.workflow_kwargs,
        )

        logger.info(
            f"Workflow continued as new: {workflow_name}",
            old_run_id=run_id,
            new_run_id=new_run_id,
        )

        return None

    except Exception as e:
        # Workflow failed
        await storage.update_run_status(run_id=run_id, status=RunStatus.FAILED, error=str(e))

        logger.error(
            f"Workflow failed: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            error=str(e),
            exc_info=True,
        )

        raise


async def _handle_continue_as_new(
    current_run_id: str,
    workflow_func: Callable,
    workflow_name: str,
    storage: StorageBackend,
    new_args: tuple,
    new_kwargs: dict,
) -> str:
    """
    Handle continue-as-new by creating new run and linking it to current.

    This is an internal function that:
    1. Generates new run_id
    2. Records WORKFLOW_CONTINUED_AS_NEW event in current run
    3. Updates current run status to CONTINUED_AS_NEW
    4. Updates current run's continued_to_run_id
    5. Creates new WorkflowRun with continued_from_run_id
    6. Starts new workflow execution via runtime

    Args:
        current_run_id: The run ID of the current workflow
        workflow_func: Workflow function
        workflow_name: Workflow name
        storage: Storage backend
        new_args: Arguments for the new workflow
        new_kwargs: Keyword arguments for the new workflow

    Returns:
        New run ID
    """
    from datetime import UTC, datetime

    from pyworkflow.config import get_config
    from pyworkflow.runtime import get_runtime

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
    parent_run_id = current_run.parent_run_id if current_run else None

    # Create new workflow run linked to current
    new_run = WorkflowRun(
        run_id=new_run_id,
        workflow_name=workflow_name,
        status=RunStatus.PENDING,
        created_at=datetime.now(UTC),
        input_args=args_json,
        input_kwargs=kwargs_json,
        continued_from_run_id=current_run_id,
        nesting_depth=nesting_depth,
        parent_run_id=parent_run_id,
    )
    await storage.create_run(new_run)

    # Start new workflow via runtime
    config = get_config()
    runtime = get_runtime(config.default_runtime)

    # Trigger execution of the new run
    await runtime.start_workflow(
        workflow_func=workflow_func,
        args=new_args,
        kwargs=new_kwargs,
        run_id=new_run_id,
        workflow_name=workflow_name,
        storage=storage,
        durable=True,
    )

    return new_run_id


async def get_workflow_run(
    run_id: str,
    storage: StorageBackend | None = None,
) -> WorkflowRun | None:
    """
    Get workflow run information.

    Args:
        run_id: Workflow run identifier
        storage: Storage backend (defaults to configured storage or FileStorageBackend)

    Returns:
        WorkflowRun if found, None otherwise
    """
    if storage is None:
        from pyworkflow.config import get_config

        config = get_config()
        storage = config.storage

    if storage is None:
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend()

    return await storage.get_run(run_id)


async def get_workflow_events(
    run_id: str,
    storage: StorageBackend | None = None,
) -> list:
    """
    Get all events for a workflow run.

    Args:
        run_id: Workflow run identifier
        storage: Storage backend (defaults to configured storage or FileStorageBackend)

    Returns:
        List of events ordered by sequence
    """
    if storage is None:
        from pyworkflow.config import get_config

        config = get_config()
        storage = config.storage

    if storage is None:
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend()

    return await storage.get_events(run_id)


async def get_workflow_chain(
    run_id: str,
    storage: StorageBackend | None = None,
) -> list[WorkflowRun]:
    """
    Get all workflow runs in a continue-as-new chain.

    Given any run_id in a chain, returns all runs from the original
    execution to the most recent continuation, ordered from oldest to newest.

    Args:
        run_id: Any run ID in the chain
        storage: Storage backend (defaults to configured storage or FileStorageBackend)

    Returns:
        List of WorkflowRun ordered from oldest to newest in the chain

    Examples:
        # Get full history of a long-running polling workflow
        chain = await get_workflow_chain("run_abc123")
        print(f"Workflow has continued {len(chain) - 1} times")
        for run in chain:
            print(f"  {run.run_id}: {run.status.value}")
    """
    if storage is None:
        from pyworkflow.config import get_config

        config = get_config()
        storage = config.storage

    if storage is None:
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend()

    return await storage.get_workflow_chain(run_id)


async def cancel_workflow(
    run_id: str,
    reason: str | None = None,
    wait: bool = False,
    timeout: float | None = None,
    storage: StorageBackend | None = None,
) -> bool:
    """
    Request cancellation of a workflow.

    Cancellation is graceful - running workflows will be cancelled at the next
    interruptible point (before a step, during sleep, etc.). The workflow can
    catch CancellationError to perform cleanup operations.

    For suspended workflows (sleeping or waiting for hook), the status is
    immediately updated to CANCELLED and a cancellation flag is set for when
    the workflow resumes.

    For running workflows, a cancellation flag is set that will be detected
    at the next cancellation check point.

    Note:
        Cancellation does NOT interrupt a step that is already executing.
        If a step takes a long time, cancellation will only be detected after
        the step completes. For long-running steps that need mid-execution
        cancellation, call ``ctx.check_cancellation()`` periodically within
        the step function.

    Args:
        run_id: Workflow run identifier
        reason: Optional reason for cancellation
        wait: If True, wait for workflow to reach terminal status
        timeout: Maximum seconds to wait (only used if wait=True)
        storage: Storage backend (defaults to configured storage)

    Returns:
        True if cancellation was initiated, False if workflow is already terminal

    Raises:
        WorkflowNotFoundError: If workflow run doesn't exist
        TimeoutError: If wait=True and timeout is exceeded

    Examples:
        # Request cancellation
        cancelled = await cancel_workflow("run_abc123")

        # Request with reason
        cancelled = await cancel_workflow(
            "run_abc123",
            reason="User requested cancellation"
        )

        # Wait for cancellation to complete
        cancelled = await cancel_workflow(
            "run_abc123",
            wait=True,
            timeout=30
        )
    """
    import asyncio

    # Resolve storage
    if storage is None:
        from pyworkflow.config import get_config

        config = get_config()
        storage = config.storage

    if storage is None:
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend()

    # Get workflow run
    run = await storage.get_run(run_id)
    if run is None:
        raise WorkflowNotFoundError(run_id)

    # Check if already in terminal state
    terminal_statuses = {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.CONTINUED_AS_NEW,
    }
    if run.status in terminal_statuses:
        logger.info(
            f"Workflow already in terminal state: {run.status.value}",
            run_id=run_id,
            status=run.status.value,
        )
        return False

    # Record cancellation requested event
    cancellation_event = create_cancellation_requested_event(
        run_id=run_id,
        reason=reason,
        requested_by="cancel_workflow",
    )
    await storage.record_event(cancellation_event)

    logger.info(
        "Cancellation requested for workflow",
        run_id=run_id,
        reason=reason,
        current_status=run.status.value,
    )

    # Handle based on current status
    if run.status == RunStatus.SUSPENDED:
        # For suspended workflows, update status to CANCELLED immediately
        # The workflow will see cancellation when it tries to resume
        cancelled_event = create_workflow_cancelled_event(
            run_id=run_id,
            reason=reason,
            cleanup_completed=False,
        )
        await storage.record_event(cancelled_event)
        await storage.update_run_status(run_id=run_id, status=RunStatus.CANCELLED)

        logger.info(
            "Suspended workflow cancelled",
            run_id=run_id,
        )

    elif run.status in {RunStatus.RUNNING, RunStatus.PENDING}:
        # For running/pending workflows, set cancellation flag
        # The workflow will detect this at the next check point
        await storage.set_cancellation_flag(run_id)

        logger.info(
            "Cancellation flag set for running workflow",
            run_id=run_id,
        )

    # Wait for terminal status if requested
    if wait:
        poll_interval = 0.5
        elapsed = 0.0
        effective_timeout = timeout or 60.0

        while elapsed < effective_timeout:
            run = await storage.get_run(run_id)
            if run and run.status in terminal_statuses:
                logger.info(
                    f"Workflow reached terminal state: {run.status.value}",
                    run_id=run_id,
                    status=run.status.value,
                )
                return True

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(
            f"Workflow {run_id} did not reach terminal state within {effective_timeout}s"
        )

    return True
