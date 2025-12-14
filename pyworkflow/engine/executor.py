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
from datetime import UTC, datetime
from typing import Any, Callable, Optional

from loguru import logger

from pyworkflow.core.exceptions import (
    SuspensionSignal,
    WorkflowAlreadyRunningError,
    WorkflowNotFoundError,
)
from pyworkflow.core.registry import get_workflow, get_workflow_by_func
from pyworkflow.core.workflow import execute_workflow_with_context
from pyworkflow.engine.events import create_workflow_started_event
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


class ConfigurationError(Exception):
    """Configuration error for PyWorkflow."""

    pass


async def start(
    workflow_func: Callable,
    *args: Any,
    runtime: Optional[str] = None,
    durable: Optional[bool] = None,
    storage: Optional[StorageBackend] = None,
    idempotency_key: Optional[str] = None,
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
        else workflow_durable if workflow_durable is not None else config.default_durable
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
        metadata=workflow_meta.metadata,
    )


async def resume(
    run_id: str,
    runtime: Optional[str] = None,
    storage: Optional[StorageBackend] = None,
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
    event_log: Optional[list] = None,
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

    except Exception as e:
        # Workflow failed
        await storage.update_run_status(
            run_id=run_id, status=RunStatus.FAILED, error=str(e)
        )

        logger.error(
            f"Workflow failed: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            error=str(e),
            exc_info=True,
        )

        raise


async def get_workflow_run(
    run_id: str,
    storage: Optional[StorageBackend] = None,
) -> Optional[WorkflowRun]:
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
    storage: Optional[StorageBackend] = None,
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
