"""
Workflow execution engine.

The executor is responsible for:
- Starting new workflow runs
- Loading and resuming existing runs
- Managing workflow lifecycle
- Coordinating with storage backend
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


async def start(
    workflow_func: Callable,
    *args: Any,
    storage: Optional[StorageBackend] = None,
    idempotency_key: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """
    Start a new workflow execution.

    This is the main entry point for starting workflows. It:
    1. Creates a new workflow run record
    2. Records the start event
    3. Executes the workflow function
    4. Handles completion or suspension

    Args:
        workflow_func: Workflow function decorated with @workflow
        *args: Positional arguments for workflow
        storage: Storage backend (defaults to FileStorageBackend)
        idempotency_key: Optional key for idempotent execution
        **kwargs: Keyword arguments for workflow

    Returns:
        run_id: Unique identifier for this workflow run

    Raises:
        WorkflowAlreadyRunningError: If idempotency key already used
        Exception: On workflow failure

    Examples:
        @workflow
        async def my_workflow(x: int):
            return x * 2

        # Start workflow
        run_id = await start(my_workflow, 42)

        # Start with idempotency
        run_id = await start(
            my_workflow,
            42,
            idempotency_key="unique-operation-id"
        )
    """
    # Get workflow metadata
    workflow_meta = get_workflow_by_func(workflow_func)
    if not workflow_meta:
        raise ValueError(
            f"Function {workflow_func.__name__} is not registered as a workflow. "
            f"Did you forget the @workflow decorator?"
        )

    workflow_name = workflow_meta.name

    # Initialize storage if not provided
    if storage is None:
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend()
        logger.warning("No storage backend provided, using FileStorageBackend")

    # Check idempotency key
    if idempotency_key:
        existing_run = await storage.get_run_by_idempotency_key(idempotency_key)
        if existing_run:
            if existing_run.status == RunStatus.RUNNING:
                raise WorkflowAlreadyRunningError(existing_run.run_id)
            logger.info(
                f"Workflow with idempotency key '{idempotency_key}' already exists",
                run_id=existing_run.run_id,
                status=existing_run.status.value,
            )
            return existing_run.run_id

    # Generate run ID
    run_id = f"run_{uuid.uuid4().hex[:16]}"

    logger.info(
        f"Starting workflow: {workflow_name}",
        run_id=run_id,
        workflow_name=workflow_name,
    )

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
        metadata=workflow_meta.metadata,
    )

    await storage.create_run(run)

    # Record workflow started event
    start_event = create_workflow_started_event(
        run_id=run_id,
        workflow_name=workflow_name,
        args=serialize_args(*args),
        kwargs=serialize_kwargs(**kwargs),
        metadata=workflow_meta.metadata,
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

        return run_id

    except SuspensionSignal as e:
        # Workflow suspended (sleep or hook)
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        logger.info(
            f"Workflow suspended: {e.reason}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )

        # TODO: Schedule resumption (via Celery or direct call)
        # For now, workflow stays suspended until manually resumed

        return run_id

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


async def resume(
    run_id: str,
    storage: Optional[StorageBackend] = None,
) -> Any:
    """
    Resume a suspended workflow.

    Loads the workflow run and event log, then continues execution
    from the suspension point.

    Args:
        run_id: Workflow run identifier
        storage: Storage backend (defaults to FileStorageBackend)

    Returns:
        Workflow result (if completed)

    Raises:
        WorkflowNotFoundError: If run_id not found
        Exception: On workflow failure
    """
    # Initialize storage if not provided
    if storage is None:
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend()

    # Load workflow run
    run = await storage.get_run(run_id)
    if not run:
        raise WorkflowNotFoundError(run_id)

    logger.info(
        f"Resuming workflow: {run.workflow_name}",
        run_id=run_id,
        workflow_name=run.workflow_name,
        current_status=run.status.value,
    )

    # Get workflow function
    workflow_meta = get_workflow(run.workflow_name)
    if not workflow_meta:
        raise ValueError(f"Workflow '{run.workflow_name}' not registered")

    # Load event log
    events = await storage.get_events(run_id)

    # Deserialize arguments
    from pyworkflow.serialization.decoder import deserialize_args, deserialize_kwargs

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
        )

        # Update run status to completed
        await storage.update_run_status(
            run_id=run_id, status=RunStatus.COMPLETED, result=serialize_args(result)
        )

        logger.info(
            f"Workflow resumed and completed: {run.workflow_name}",
            run_id=run_id,
            workflow_name=run.workflow_name,
        )

        return result

    except SuspensionSignal as e:
        # Workflow suspended again
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        logger.info(
            f"Workflow suspended again: {e.reason}",
            run_id=run_id,
            workflow_name=run.workflow_name,
            reason=e.reason,
        )

        return None

    except Exception as e:
        # Workflow failed
        await storage.update_run_status(
            run_id=run_id, status=RunStatus.FAILED, error=str(e)
        )

        logger.error(
            f"Workflow failed on resume: {run.workflow_name}",
            run_id=run_id,
            workflow_name=run.workflow_name,
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
        storage: Storage backend (defaults to FileStorageBackend)

    Returns:
        WorkflowRun if found, None otherwise
    """
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
        storage: Storage backend (defaults to FileStorageBackend)

    Returns:
        List of events ordered by sequence
    """
    if storage is None:
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend()

    return await storage.get_events(run_id)
