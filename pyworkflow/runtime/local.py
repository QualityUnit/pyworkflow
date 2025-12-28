"""
Local runtime - executes workflows in-process.

The local runtime is ideal for:
- CI/CD pipelines
- Local development
- Testing
- Simple scripts that don't need distributed execution
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from pyworkflow.core.exceptions import (
    CancellationError,
    ContinueAsNewSignal,
    SuspensionSignal,
    WorkflowNotFoundError,
)
from pyworkflow.runtime.base import Runtime

if TYPE_CHECKING:
    from pyworkflow.storage.base import StorageBackend
    from pyworkflow.storage.schemas import RunStatus


async def _handle_parent_completion_local(
    run_id: str,
    status: "RunStatus",
    storage: "StorageBackend",
) -> None:
    """
    Handle parent workflow completion by cancelling all running children.

    When a parent workflow reaches a terminal state (COMPLETED, FAILED, CANCELLED),
    all running child workflows are automatically cancelled. This implements the
    TERMINATE parent close policy.
    """
    from pyworkflow.engine.events import EventType, create_child_workflow_cancelled_event
    from pyworkflow.engine.executor import cancel_workflow
    from pyworkflow.storage.schemas import RunStatus

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

    for child in running_children:
        try:
            reason = f"Parent workflow {run_id} {status.value}"

            await cancel_workflow(
                run_id=child.run_id,
                reason=reason,
                storage=storage,
            )

            # Find child_id from parent's events
            events = await storage.get_events(run_id)
            child_id = None
            for event in events:
                if (
                    event.type == EventType.CHILD_WORKFLOW_STARTED
                    and event.data.get("child_run_id") == child.run_id
                ):
                    child_id = event.data.get("child_id")
                    break

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
            )

        except Exception as e:
            logger.error(
                f"Failed to cancel child workflow: {child.workflow_name}",
                parent_run_id=run_id,
                child_run_id=child.run_id,
                error=str(e),
            )


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
        idempotency_key: str | None = None,
        max_duration: str | None = None,
        metadata: dict | None = None,
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
            # Check if run already exists (e.g., from continue_as_new)
            existing_run = await storage.get_run(run_id)
            if existing_run:
                # Run was pre-created (e.g., by _handle_continue_as_new)
                # Just update status to RUNNING
                await storage.update_run_status(run_id=run_id, status=RunStatus.RUNNING)
            else:
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
                    context=metadata or {},
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

                # Cancel all running children (TERMINATE policy)
                await _handle_parent_completion_local(run_id, RunStatus.COMPLETED, storage)

            logger.info(
                f"Workflow completed: {workflow_name}",
                run_id=run_id,
                workflow_name=workflow_name,
                durable=durable,
            )

            return run_id

        except CancellationError as e:
            if durable and storage is not None:
                from pyworkflow.engine.events import create_workflow_cancelled_event

                cancelled_event = create_workflow_cancelled_event(
                    run_id=run_id,
                    reason=e.reason,
                    cleanup_completed=True,
                )
                await storage.record_event(cancelled_event)
                await storage.update_run_status(run_id=run_id, status=RunStatus.CANCELLED)
                await storage.clear_cancellation_flag(run_id)

                # Cancel all running children (TERMINATE policy)
                await _handle_parent_completion_local(run_id, RunStatus.CANCELLED, storage)

            logger.info(
                f"Workflow cancelled: {workflow_name}",
                run_id=run_id,
                workflow_name=workflow_name,
                reason=e.reason,
            )

            return run_id

        except SuspensionSignal as e:
            if durable and storage is not None:
                # Workflow suspended (sleep, hook, or retry)
                await storage.update_run_status(run_id=run_id, status=RunStatus.SUSPENDED)

            # Enhanced logging for retry suspensions
            if e.reason.startswith("retry:"):
                step_id = e.data.get("step_id") if e.data else "unknown"
                attempt = e.data.get("attempt") if e.data else "?"
                resume_at = e.data.get("resume_at") if e.data else "unknown"
                logger.info(
                    "Workflow suspended for step retry",
                    run_id=run_id,
                    workflow_name=workflow_name,
                    step_id=step_id,
                    next_attempt=attempt,
                    resume_at=resume_at,
                )
            else:
                logger.info(
                    f"Workflow suspended: {e.reason}",
                    run_id=run_id,
                    workflow_name=workflow_name,
                    reason=e.reason,
                )

            return run_id

        except ContinueAsNewSignal as e:
            # Workflow continuing as new execution
            if durable and storage is not None:
                from pyworkflow.engine.executor import _handle_continue_as_new
                from pyworkflow.storage.schemas import RunStatus as RS

                # Cancel all running children (TERMINATE policy)
                await _handle_parent_completion_local(run_id, RS.CONTINUED_AS_NEW, storage)

                # Handle the continuation
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
                    run_id=run_id,
                    workflow_name=workflow_name,
                    new_run_id=new_run_id,
                )

            return run_id

        except Exception as e:
            if durable and storage is not None:
                # Workflow failed
                await storage.update_run_status(
                    run_id=run_id, status=RunStatus.FAILED, error=str(e)
                )

                # Cancel all running children (TERMINATE policy)
                await _handle_parent_completion_local(run_id, RunStatus.FAILED, storage)

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

            # Cancel all running children (TERMINATE policy)
            await _handle_parent_completion_local(run_id, RunStatus.COMPLETED, storage)

            logger.info(
                f"Workflow resumed and completed: {run.workflow_name}",
                run_id=run_id,
                workflow_name=run.workflow_name,
            )

            return result

        except CancellationError as e:
            from pyworkflow.engine.events import create_workflow_cancelled_event

            cancelled_event = create_workflow_cancelled_event(
                run_id=run_id,
                reason=e.reason,
                cleanup_completed=True,
            )
            await storage.record_event(cancelled_event)
            await storage.update_run_status(run_id=run_id, status=RunStatus.CANCELLED)
            await storage.clear_cancellation_flag(run_id)

            # Cancel all running children (TERMINATE policy)
            await _handle_parent_completion_local(run_id, RunStatus.CANCELLED, storage)

            logger.info(
                f"Workflow cancelled on resume: {run.workflow_name}",
                run_id=run_id,
                workflow_name=run.workflow_name,
                reason=e.reason,
            )

            return None

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

        except ContinueAsNewSignal as e:
            # Workflow continuing as new execution
            from pyworkflow.engine.executor import _handle_continue_as_new

            # Cancel all running children (TERMINATE policy)
            await _handle_parent_completion_local(run_id, RunStatus.CONTINUED_AS_NEW, storage)

            # Handle the continuation
            new_run_id = await _handle_continue_as_new(
                current_run_id=run_id,
                workflow_func=workflow_meta.func,
                workflow_name=run.workflow_name,
                storage=storage,
                new_args=e.workflow_args,
                new_kwargs=e.workflow_kwargs,
            )

            logger.info(
                f"Workflow continued as new on resume: {run.workflow_name}",
                run_id=run_id,
                workflow_name=run.workflow_name,
                new_run_id=new_run_id,
            )

            return None

        except Exception as e:
            # Workflow failed
            await storage.update_run_status(run_id=run_id, status=RunStatus.FAILED, error=str(e))

            # Cancel all running children (TERMINATE policy)
            await _handle_parent_completion_local(run_id, RunStatus.FAILED, storage)

            logger.error(
                f"Workflow failed on resume: {run.workflow_name}",
                run_id=run_id,
                workflow_name=run.workflow_name,
                error=str(e),
                exc_info=True,
            )

            raise

    async def schedule_resume(
        self,
        run_id: str,
        storage: "StorageBackend",
    ) -> None:
        """
        Schedule immediate workflow resumption.

        For local runtime, this directly calls resume_workflow since
        execution happens in-process.
        """
        logger.info(
            f"Scheduling immediate workflow resume: {run_id}",
            run_id=run_id,
        )

        try:
            await self.resume_workflow(run_id, storage)
        except Exception as e:
            logger.error(
                f"Failed to resume workflow: {e}",
                run_id=run_id,
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

    async def start_child_workflow(
        self,
        workflow_func: Callable[..., Any],
        args: tuple,
        kwargs: dict,
        child_run_id: str,
        workflow_name: str,
        storage: "StorageBackend",
        parent_run_id: str,
        child_id: str,
        wait_for_completion: bool,
    ) -> None:
        """
        Start a child workflow in the background (fire-and-forget).

        Uses asyncio.create_task to run the child workflow asynchronously
        so the caller returns immediately.
        """
        import asyncio

        asyncio.create_task(
            self._execute_child_workflow(
                workflow_func=workflow_func,
                args=args,
                kwargs=kwargs,
                child_run_id=child_run_id,
                workflow_name=workflow_name,
                storage=storage,
                parent_run_id=parent_run_id,
                child_id=child_id,
                wait_for_completion=wait_for_completion,
            )
        )

    async def _execute_child_workflow(
        self,
        workflow_func: Callable[..., Any],
        args: tuple,
        kwargs: dict,
        child_run_id: str,
        workflow_name: str,
        storage: "StorageBackend",
        parent_run_id: str,
        child_id: str,
        wait_for_completion: bool,
    ) -> None:
        """
        Execute a child workflow and notify parent on completion.

        This runs in the background and handles:
        1. Executing the child workflow
        2. Recording completion/failure events in parent's log
        3. Triggering parent resumption if waiting
        """
        from pyworkflow.core.workflow import execute_workflow_with_context
        from pyworkflow.engine.events import (
            create_child_workflow_completed_event,
            create_child_workflow_failed_event,
        )
        from pyworkflow.serialization.encoder import serialize
        from pyworkflow.storage.schemas import RunStatus

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
            )

            # Update status to COMPLETED
            serialized_result = serialize(result)
            await storage.update_run_status(
                child_run_id, RunStatus.COMPLETED, result=serialized_result
            )

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
                await self._trigger_parent_resumption(parent_run_id, storage)

        except SuspensionSignal:
            # Child workflow suspended (e.g., sleep, hook)
            # Update status and don't notify parent yet - handled on child resumption
            await storage.update_run_status(child_run_id, RunStatus.SUSPENDED)
            logger.debug(
                f"Child workflow suspended: {workflow_name}",
                parent_run_id=parent_run_id,
                child_run_id=child_run_id,
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
                await self._trigger_parent_resumption(parent_run_id, storage)

    async def _trigger_parent_resumption(
        self,
        parent_run_id: str,
        storage: "StorageBackend",
    ) -> None:
        """
        Trigger parent workflow resumption after child completes.

        Checks if parent is suspended and resumes it.
        """
        from pyworkflow.storage.schemas import RunStatus

        parent_run = await storage.get_run(parent_run_id)
        if parent_run and parent_run.status == RunStatus.SUSPENDED:
            logger.debug(
                "Triggering parent resumption",
                parent_run_id=parent_run_id,
            )
            # Resume the parent workflow directly (we're already in a background task)
            await self.resume_workflow(parent_run_id, storage=storage)


async def resume(
    run_id: str,
    storage: Optional["StorageBackend"] = None,
) -> Any:
    """
    Resume a suspended workflow using the local runtime.

    This is a convenience function for resuming workflows without
    explicitly creating a LocalRuntime instance.

    Args:
        run_id: Workflow run ID to resume
        storage: Storage backend (uses configured default if None)

    Returns:
        Workflow result if completed, None if suspended again

    Raises:
        WorkflowNotFoundError: If workflow run doesn't exist
    """
    if storage is None:
        from pyworkflow.config import get_config

        config = get_config()
        storage = config.storage

        if storage is None:
            from pyworkflow.storage.file import FileStorageBackend

            storage = FileStorageBackend()

    runtime = LocalRuntime()
    return await runtime.resume_workflow(run_id=run_id, storage=storage)
