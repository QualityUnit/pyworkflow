"""
Celery runtime - executes workflows on distributed Celery workers.

The Celery runtime is ideal for:
- Production deployments
- Distributed execution across multiple workers
- Long-running workflows with sleeps and webhooks
- High availability and scalability
"""

import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

from loguru import logger

from pyworkflow.runtime.base import Runtime

if TYPE_CHECKING:
    from pyworkflow.storage.base import StorageBackend


class CeleryRuntime(Runtime):
    """
    Execute workflows on distributed Celery workers.

    This runtime dispatches workflow execution to Celery workers,
    enabling distributed processing and automatic resumption of
    suspended workflows.

    Note: This runtime only supports durable workflows since
    Celery execution requires state persistence for proper
    task routing and resumption.
    """

    def __init__(
        self,
        broker_url: Optional[str] = None,
        result_backend: Optional[str] = None,
    ):
        """
        Initialize Celery runtime.

        Args:
            broker_url: Celery broker URL (default: from env or redis://localhost:6379/0)
            result_backend: Result backend URL (default: from env or redis://localhost:6379/1)
        """
        self._broker_url = broker_url or os.getenv(
            "PYWORKFLOW_CELERY_BROKER", "redis://localhost:6379/0"
        )
        self._result_backend = result_backend or os.getenv(
            "PYWORKFLOW_CELERY_RESULT_BACKEND", "redis://localhost:6379/1"
        )

    @property
    def name(self) -> str:
        return "celery"

    @property
    def supports_durable(self) -> bool:
        return True

    @property
    def supports_transient(self) -> bool:
        # Celery runtime requires durable workflows for proper state management
        return False

    @property
    def broker_url(self) -> str:
        """Get the configured broker URL."""
        return self._broker_url

    @property
    def result_backend(self) -> str:
        """Get the configured result backend URL."""
        return self._result_backend

    def _get_storage_config(self, storage: Optional["StorageBackend"]) -> Optional[dict]:
        """
        Convert storage backend to configuration dict for Celery tasks.

        Args:
            storage: Storage backend instance

        Returns:
            Configuration dict or None
        """
        if storage is None:
            return None

        # Determine storage type and extract configuration
        storage_class_name = storage.__class__.__name__

        if storage_class_name == "FileStorageBackend":
            base_path = getattr(storage, "base_path", None)
            return {
                "type": "file",
                "base_path": str(base_path) if base_path else None,
            }
        elif storage_class_name == "RedisStorageBackend":
            return {
                "type": "redis",
                "host": getattr(storage, "host", "localhost"),
                "port": getattr(storage, "port", 6379),
                "db": getattr(storage, "db", 0),
            }
        elif storage_class_name == "InMemoryStorageBackend":
            # In-memory storage cannot be shared across workers
            # Fall back to file storage
            logger.warning(
                "InMemoryStorageBackend cannot be used with Celery runtime. "
                "Falling back to FileStorageBackend."
            )
            return {"type": "file"}
        else:
            # Default to file storage
            return {"type": "file"}

    async def start_workflow(
        self,
        workflow_func: Callable[..., Any],
        args: tuple,
        kwargs: dict,
        run_id: str,
        workflow_name: str,
        storage: Optional["StorageBackend"],
        durable: bool,
        idempotency_key: Optional[str] = None,
        max_duration: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Start a workflow execution by dispatching to Celery workers.

        The workflow will be queued and executed by an available worker.
        """
        from pyworkflow.celery.tasks import start_workflow_task
        from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs

        if not durable:
            raise ValueError(
                "Celery runtime requires durable=True. "
                "Use the 'local' runtime for transient workflows."
            )

        logger.info(
            f"Dispatching workflow to Celery: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
        )

        # Serialize arguments for Celery transport
        args_json = serialize_args(*args)
        kwargs_json = serialize_kwargs(**kwargs)

        # Get storage configuration for workers
        storage_config = self._get_storage_config(storage)

        # Dispatch to Celery worker
        task_result = start_workflow_task.delay(
            workflow_name=workflow_name,
            args_json=args_json,
            kwargs_json=kwargs_json,
            run_id=run_id,
            storage_config=storage_config,
            idempotency_key=idempotency_key,
        )

        logger.info(
            f"Workflow dispatched to Celery: {workflow_name}",
            run_id=run_id,
            task_id=task_result.id,
        )

        # Return the run_id (the actual run_id is generated by the worker)
        # For now, we return a pending status indicator
        # The actual run_id can be obtained from the task result
        return run_id

    async def resume_workflow(
        self,
        run_id: str,
        storage: "StorageBackend",
    ) -> Any:
        """
        Resume a suspended workflow by dispatching to Celery workers.
        """
        from pyworkflow.celery.tasks import resume_workflow_task

        logger.info(
            f"Dispatching workflow resume to Celery: {run_id}",
            run_id=run_id,
        )

        # Get storage configuration for workers
        storage_config = self._get_storage_config(storage)

        # Dispatch to Celery worker
        task_result = resume_workflow_task.delay(
            run_id=run_id,
            storage_config=storage_config,
        )

        logger.info(
            f"Workflow resume dispatched to Celery: {run_id}",
            run_id=run_id,
            task_id=task_result.id,
        )

        # Return None since the actual result will be available asynchronously
        return None

    async def schedule_wake(
        self,
        run_id: str,
        wake_time: datetime,
        storage: "StorageBackend",
    ) -> None:
        """
        Schedule workflow resumption at a specific time using Celery.

        Uses Celery's countdown feature to delay task execution.
        """
        from pyworkflow.celery.tasks import schedule_workflow_resumption

        logger.info(
            f"Scheduling workflow wake via Celery: {run_id}",
            run_id=run_id,
            wake_time=wake_time.isoformat(),
        )

        # Use the existing schedule function which handles the delay calculation
        schedule_workflow_resumption(run_id, wake_time)

        logger.info(
            f"Workflow wake scheduled: {run_id}",
            run_id=run_id,
            wake_time=wake_time.isoformat(),
        )
