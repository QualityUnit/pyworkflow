"""
Celery tasks for distributed workflow and step execution.

These tasks enable:
- Distributed step execution across workers
- Automatic retry with exponential backoff
- Scheduled sleep resumption
- Workflow orchestration
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from celery import Task
from loguru import logger

from pyworkflow.celery.app import celery_app
from pyworkflow.core.exceptions import FatalError, RetryableError, SuspensionSignal
from pyworkflow.core.registry import get_workflow, get_workflow_by_func
from pyworkflow.core.workflow import execute_workflow_with_context
from pyworkflow.engine.events import create_workflow_started_event
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
        """Handle task failure."""
        logger.error(
            f"Task {self.name} failed",
            task_id=task_id,
            error=str(exc),
            traceback=einfo.traceback,
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
    self,
    step_name: str,
    args_json: str,
    kwargs_json: str,
    run_id: str,
    step_id: str,
    max_retries: int = 3,
    storage_config: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Execute a workflow step in a Celery worker.

    This task runs a single step and handles retries automatically.

    Args:
        step_name: Name of the step function
        args_json: Serialized positional arguments
        kwargs_json: Serialized keyword arguments
        run_id: Workflow run ID
        step_id: Step execution ID
        max_retries: Maximum retry attempts
        storage_config: Storage backend configuration

    Returns:
        Step result (serialized)

    Raises:
        FatalError: For non-retriable errors
        RetryableError: For retriable errors (triggers automatic retry)
    """
    from pyworkflow.core.registry import _registry

    logger.info(
        f"Executing step: {step_name}",
        run_id=run_id,
        step_id=step_id,
        attempt=self.request.retries + 1,
    )

    # Get step metadata
    step_meta = _registry.get_step(step_name)
    if not step_meta:
        raise FatalError(f"Step '{step_name}' not found in registry")

    # Deserialize arguments
    args = deserialize_args(args_json)
    kwargs = deserialize_kwargs(kwargs_json)

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

        return result

    except FatalError:
        logger.error(f"Step failed (fatal): {step_name}", run_id=run_id, step_id=step_id)
        raise

    except RetryableError as e:
        logger.warning(
            f"Step failed (retriable): {step_name}",
            run_id=run_id,
            step_id=step_id,
            retry_after=e.retry_after,
        )
        # Let Celery handle the retry
        raise self.retry(exc=e, countdown=e.get_retry_delay_seconds() or 60)

    except Exception as e:
        logger.error(
            f"Step failed (unexpected): {step_name}",
            run_id=run_id,
            step_id=step_id,
            error=str(e),
            exc_info=True,
        )
        # Treat unexpected errors as retriable
        raise self.retry(exc=RetryableError(str(e)), countdown=60)


@celery_app.task(
    name="pyworkflow.start_workflow",
    queue="pyworkflow.workflows",
)
def start_workflow_task(
    workflow_name: str,
    args_json: str,
    kwargs_json: str,
    storage_config: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> str:
    """
    Start a workflow execution.

    This task executes on Celery workers and runs the workflow directly.

    Args:
        workflow_name: Name of the workflow
        args_json: Serialized positional arguments
        kwargs_json: Serialized keyword arguments
        storage_config: Storage backend configuration
        idempotency_key: Optional idempotency key

    Returns:
        Workflow run ID
    """
    logger.info(f"Starting workflow on worker: {workflow_name}")

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
    run_id = asyncio.run(
        _start_workflow_on_worker(
            workflow_meta=workflow_meta,
            args=args,
            kwargs=kwargs,
            storage=storage,
            idempotency_key=idempotency_key,
        )
    )

    logger.info(f"Workflow execution initiated: {workflow_name}", run_id=run_id)
    return run_id


async def _start_workflow_on_worker(
    workflow_meta,
    args: tuple,
    kwargs: dict,
    storage: StorageBackend,
    idempotency_key: Optional[str] = None,
) -> str:
    """
    Internal function to start workflow on Celery worker.

    This mirrors the logic from testing.py but runs on workers.
    """
    from pyworkflow.core.exceptions import WorkflowAlreadyRunningError

    workflow_name = workflow_meta.name

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
        f"Starting workflow execution on worker: {workflow_name}",
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
            f"Workflow completed successfully on worker: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
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

        return run_id

    except Exception as e:
        # Workflow failed
        await storage.update_run_status(
            run_id=run_id, status=RunStatus.FAILED, error=str(e)
        )

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
    storage_config: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
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
    result = asyncio.run(_resume_workflow_on_worker(run_id, storage))

    if result is not None:
        logger.info(f"Workflow completed on worker: {run_id}")
    else:
        logger.info(f"Workflow suspended again on worker: {run_id}")

    return result


async def _resume_workflow_on_worker(
    run_id: str,
    storage: StorageBackend,
) -> Optional[Any]:
    """
    Internal function to resume workflow on Celery worker.

    This mirrors the logic from testing.py but runs on workers.
    """
    from pyworkflow.core.exceptions import WorkflowNotFoundError

    # Load workflow run
    run = await storage.get_run(run_id)
    if not run:
        raise WorkflowNotFoundError(run_id)

    logger.info(
        f"Resuming workflow execution on worker: {run.workflow_name}",
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
            f"Workflow resumed and completed on worker: {run.workflow_name}",
            run_id=run_id,
            workflow_name=run.workflow_name,
        )

        return result

    except SuspensionSignal as e:
        # Workflow suspended again
        await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

        logger.info(
            f"Workflow suspended again on worker: {e.reason}",
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
            f"Workflow failed on resume on worker: {run.workflow_name}",
            run_id=run_id,
            workflow_name=run.workflow_name,
            error=str(e),
            exc_info=True,
        )

        raise


def _get_storage_backend(config: Optional[Dict[str, Any]] = None) -> StorageBackend:
    """
    Get storage backend from configuration.

    Args:
        config: Storage configuration dict with 'type' and other parameters

    Returns:
        Storage backend instance
    """
    if not config:
        # Default to FileStorageBackend
        from pyworkflow.storage.file import FileStorageBackend

        return FileStorageBackend()

    storage_type = config.get("type", "file")

    if storage_type == "file":
        from pyworkflow.storage.file import FileStorageBackend

        return FileStorageBackend(base_path=config.get("base_path"))

    elif storage_type == "redis":
        from pyworkflow.storage.redis import RedisStorageBackend

        return RedisStorageBackend(
            host=config.get("host", "localhost"),
            port=config.get("port", 6379),
            db=config.get("db", 0),
        )

    else:
        raise ValueError(f"Unknown storage type: {storage_type}")


def schedule_workflow_resumption(run_id: str, resume_at: datetime) -> None:
    """
    Schedule automatic workflow resumption after sleep.

    Args:
        run_id: Workflow run ID
        resume_at: When to resume the workflow
    """
    from datetime import UTC

    # Calculate delay in seconds
    now = datetime.now(UTC)
    delay_seconds = max(0, int((resume_at - now).total_seconds()))

    logger.info(
        f"Scheduling workflow resumption",
        run_id=run_id,
        resume_at=resume_at.isoformat(),
        delay_seconds=delay_seconds,
    )

    # Schedule the resume task
    resume_workflow_task.apply_async(
        args=[run_id],
        countdown=delay_seconds,
    )
