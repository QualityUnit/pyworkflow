"""
Local runtime - executes workflows in-process.

The local runtime is ideal for:
- CI/CD pipelines
- Local development
- Testing
- Simple scripts that don't need distributed execution
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

from loguru import logger

from pyworkflow.core.exceptions import SuspensionSignal, WorkflowNotFoundError
from pyworkflow.runtime.base import Runtime

if TYPE_CHECKING:
    from pyworkflow.storage.base import StorageBackend


class LocalRuntime(Runtime):
    """
    Execute workflows directly in the current process.

    This runtime supports both durable and transient workflows:
    - Durable: Events are recorded, workflows can be resumed
    - Transient: No persistence, simple execution
    """

    @property
    def name(self) -> str:
        return "local"

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
        """Start a workflow execution in the current process."""
        from pyworkflow.core.workflow import execute_workflow_with_context
        from pyworkflow.engine.events import create_workflow_started_event
        from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
        from pyworkflow.storage.schemas import RunStatus, WorkflowRun

        logger.info(
            f"Starting workflow locally: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            durable=durable,
        )

        if durable and storage is not None:
            # Create workflow run record
            workflow_run = WorkflowRun(
                run_id=run_id,
                workflow_name=workflow_name,
                status=RunStatus.RUNNING,
                created_at=datetime.now(UTC),
                started_at=datetime.now(UTC),
                input_args=serialize_args(*args),
                input_kwargs=serialize_kwargs(**kwargs),
                idempotency_key=idempotency_key,
                max_duration=max_duration,
                metadata=metadata or {},
            )
            await storage.create_run(workflow_run)

            # Record start event
            event = create_workflow_started_event(
                run_id=run_id,
                workflow_name=workflow_name,
                args=serialize_args(*args),
                kwargs=serialize_kwargs(**kwargs),
            )
            await storage.record_event(event)

        # Execute workflow
        try:
            result = await execute_workflow_with_context(
                workflow_func=workflow_func,
                run_id=run_id,
                workflow_name=workflow_name,
                storage=storage if durable else None,
                args=args,
                kwargs=kwargs,
                durable=durable,
            )

            if durable and storage is not None:
                # Update run status to completed
                await storage.update_run_status(
                    run_id=run_id,
                    status=RunStatus.COMPLETED,
                    result=serialize_args(result),
                )

            logger.info(
                f"Workflow completed: {workflow_name}",
                run_id=run_id,
                workflow_name=workflow_name,
                durable=durable,
            )

            return run_id

        except SuspensionSignal as e:
            if durable and storage is not None:
                # Workflow suspended (sleep or hook)
                await storage.update_run_status(
                    run_id=run_id, status=RunStatus.SUSPENDED
                )

            logger.info(
                f"Workflow suspended: {e.reason}",
                run_id=run_id,
                workflow_name=workflow_name,
                reason=e.reason,
            )

            return run_id

        except Exception as e:
            if durable and storage is not None:
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

    async def resume_workflow(
        self,
        run_id: str,
        storage: "StorageBackend",
    ) -> Any:
        """Resume a suspended workflow."""
        from pyworkflow.core.registry import get_workflow
        from pyworkflow.core.workflow import execute_workflow_with_context
        from pyworkflow.serialization.decoder import deserialize_args, deserialize_kwargs
        from pyworkflow.serialization.encoder import serialize_args
        from pyworkflow.storage.schemas import RunStatus

        # Load workflow run
        run = await storage.get_run(run_id)
        if not run:
            raise WorkflowNotFoundError(run_id)

        logger.info(
            f"Resuming workflow locally: {run.workflow_name}",
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
                durable=True,  # Resume is always durable
            )

            # Update run status to completed
            await storage.update_run_status(
                run_id=run_id,
                status=RunStatus.COMPLETED,
                result=serialize_args(result),
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

    async def schedule_wake(
        self,
        run_id: str,
        wake_time: datetime,
        storage: "StorageBackend",
    ) -> None:
        """
        Schedule workflow resumption at a specific time.

        Note: Local runtime cannot auto-schedule wake-ups.
        User must manually call resume().
        """
        logger.info(
            f"Workflow {run_id} suspended until {wake_time}. "
            "Call resume() manually to continue (local runtime does not support auto-wake).",
            run_id=run_id,
            wake_time=wake_time.isoformat(),
        )
