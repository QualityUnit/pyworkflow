"""
Workflow execution engine.

The executor is responsible for:
- Starting new workflow runs (distributed via Celery)
- Resuming existing runs (distributed via Celery)
- Managing workflow lifecycle
- Coordinating with storage backend

All workflows execute in distributed mode using Celery workers.
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


def start(
    workflow_func: Callable,
    *args: Any,
    storage_config: Optional[dict] = None,
    idempotency_key: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """
    Start a new workflow execution in distributed mode.

    Workflows execute across Celery workers, enabling:
    - Horizontal scaling across multiple machines
    - Fault tolerance through event sourcing
    - Automatic sleep resumption via Celery Beat
    - Zero-resource suspension

    Args:
        workflow_func: Workflow function decorated with @workflow
        *args: Positional arguments for workflow
        storage_config: Storage backend configuration (optional)
        idempotency_key: Optional key for idempotent execution
        **kwargs: Keyword arguments for workflow

    Returns:
        run_id: Unique identifier for this workflow run

    Examples:
        @workflow
        async def my_workflow(x: int):
            result = await my_step(x)
            await sleep("5m")
            return result

        # Start workflow - executes on Celery workers
        run_id = start(my_workflow, 42)

        # With idempotency
        run_id = start(
            my_workflow,
            42,
            idempotency_key="unique-operation-id"
        )

        # With custom storage (Redis)
        run_id = start(
            my_workflow,
            42,
            storage_config={"type": "redis", "host": "localhost"}
        )
    """
    from pyworkflow.celery.tasks import start_workflow_task

    # Get workflow metadata
    workflow_meta = get_workflow_by_func(workflow_func)
    if not workflow_meta:
        raise ValueError(
            f"Function {workflow_func.__name__} is not registered as a workflow. "
            f"Did you forget the @workflow decorator?"
        )

    workflow_name = workflow_meta.name

    # Serialize arguments
    args_json = serialize_args(*args)
    kwargs_json = serialize_kwargs(**kwargs)

    logger.info(
        f"Starting workflow in distributed mode: {workflow_name}",
        workflow_name=workflow_name,
        idempotency_key=idempotency_key,
    )

    # Submit to Celery - execution happens on workers
    result = start_workflow_task.delay(
        workflow_name=workflow_name,
        args_json=args_json,
        kwargs_json=kwargs_json,
        storage_config=storage_config,
        idempotency_key=idempotency_key,
    )

    # Wait for workflow to start and get run_id
    try:
        run_id = result.get(timeout=30)
    except Exception as e:
        logger.error(
            f"Failed to start workflow: {workflow_name}",
            error=str(e),
            exc_info=True,
        )
        raise

    logger.info(
        f"Workflow started in distributed mode: {workflow_name}",
        run_id=run_id,
        task_id=result.id,
    )

    return run_id


def resume(
    run_id: str,
    storage_config: Optional[dict] = None,
) -> None:
    """
    Resume a suspended workflow in distributed mode.

    Submits the workflow resumption to Celery workers. The workflow
    will continue execution from where it was suspended.

    Args:
        run_id: Workflow run identifier
        storage_config: Storage backend configuration (optional)

    Examples:
        # Resume a workflow after manual intervention
        resume("run_abc123")

        # Resume with custom storage
        resume("run_abc123", storage_config={"type": "redis"})

    Note:
        When using sleep() with Celery Beat running, workflows
        automatically resume - manual resume() is not needed.
    """
    from pyworkflow.celery.tasks import resume_workflow_task

    logger.info(f"Resuming workflow in distributed mode: {run_id}")

    # Submit to Celery - execution happens on workers
    resume_workflow_task.delay(
        run_id=run_id,
        storage_config=storage_config,
    )

    logger.info(
        f"Workflow resume submitted to workers",
        run_id=run_id,
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
