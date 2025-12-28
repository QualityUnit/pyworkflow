"""
start_child_workflow() primitive for spawning child workflows.

Child workflows have their own run_id and event history but are linked
to their parent for lifecycle management. When parent completes/fails/cancels,
all running children are automatically cancelled (TERMINATE policy).
"""

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from pyworkflow.context import get_context, has_context
from pyworkflow.core.exceptions import (
    ChildWorkflowFailedError,
    MaxNestingDepthError,
    SuspensionSignal,
)
from pyworkflow.core.registry import get_workflow_by_func
from pyworkflow.engine.events import create_child_workflow_started_event
from pyworkflow.primitives.child_handle import ChildWorkflowHandle
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.schemas import RunStatus, WorkflowRun

if TYPE_CHECKING:
    from pyworkflow.core.registry import WorkflowMetadata


MAX_NESTING_DEPTH = 3


async def start_child_workflow(
    workflow_func: Callable,
    *args: Any,
    wait_for_completion: bool = True,
    **kwargs: Any,
) -> Any | ChildWorkflowHandle:
    """
    Start a child workflow from within a parent workflow.

    Child workflows have their own run_id and event history but are linked
    to the parent for lifecycle management. When the parent completes, fails,
    or is cancelled, all running children are automatically cancelled.

    Args:
        workflow_func: Workflow function decorated with @workflow
        *args: Positional arguments for the child workflow
        wait_for_completion: If True, suspend until child completes and return result.
            If False, return ChildWorkflowHandle immediately for fire-and-forget.
        **kwargs: Keyword arguments for the child workflow

    Returns:
        If wait_for_completion=True: Child workflow result
        If wait_for_completion=False: ChildWorkflowHandle

    Raises:
        RuntimeError: If called outside workflow context
        MaxNestingDepthError: If max nesting depth (3) exceeded
        ChildWorkflowFailedError: If wait_for_completion=True and child fails
        ValueError: If workflow_func is not a registered workflow

    Examples:
        # Wait for child to complete (default)
        result = await start_child_workflow(process_order, order_id)

        # Fire-and-forget with handle
        handle = await start_child_workflow(
            send_notifications,
            order_id,
            wait_for_completion=False
        )

        # Check status or get result later
        if await handle.get_status() == RunStatus.COMPLETED:
            result = await handle.result()

        # Or cancel if needed
        await handle.cancel()
    """
    if not has_context():
        raise RuntimeError(
            "start_child_workflow() must be called within a workflow context. "
            "Make sure you're using the @workflow decorator."
        )

    ctx = get_context()

    # Validate storage is available (required for child workflows)
    storage = ctx.storage
    if storage is None:
        raise RuntimeError(
            "start_child_workflow() requires durable mode with storage. "
            "Make sure you have configured a storage backend."
        )

    # Check for cancellation before starting child
    ctx.check_cancellation()

    # Get workflow metadata
    workflow_meta = get_workflow_by_func(workflow_func)
    if not workflow_meta:
        raise ValueError(
            f"Function {workflow_func.__name__} is not registered as a workflow. "
            f"Did you forget the @workflow decorator?"
        )

    child_workflow_name = workflow_meta.name

    # Enforce max nesting depth
    current_depth = await storage.get_nesting_depth(ctx.run_id)
    if current_depth >= MAX_NESTING_DEPTH:
        raise MaxNestingDepthError(current_depth)

    # Generate deterministic child_id (like step_id)
    child_id = _generate_child_id(child_workflow_name, args, kwargs)

    # Check if child already completed (replay from events)
    if ctx.has_child_result(child_id):
        logger.debug(
            f"[replay] Child workflow {child_id} already completed",
            run_id=ctx.run_id,
            child_id=child_id,
        )
        cached = ctx.get_child_result(child_id)

        if wait_for_completion:
            # Check if it was a failure
            if cached.get("__failed__"):
                raise ChildWorkflowFailedError(
                    child_run_id=cached["child_run_id"],
                    child_workflow_name=child_workflow_name,
                    error=cached["error"],
                    error_type=cached["error_type"],
                )
            return cached["result"]
        else:
            # Return handle to existing child
            return ChildWorkflowHandle(
                child_id=child_id,
                child_run_id=cached["child_run_id"],
                child_workflow_name=child_workflow_name,
                parent_run_id=ctx.run_id,
                _storage=storage,
            )

    # Check if child is pending (started but not completed in events)
    # This can happen during recovery - the child might still be running
    # or might have completed while we were recovering
    if child_id in ctx.pending_children:
        existing_child_run_id = ctx.pending_children[child_id]
        child_run = await storage.get_run(existing_child_run_id)

        if child_run:
            logger.debug(
                f"[recovery] Found pending child {child_id} with status {child_run.status}",
                run_id=ctx.run_id,
                child_run_id=existing_child_run_id,
            )

            if child_run.status == RunStatus.COMPLETED:
                # Child completed while we were recovering - use its result
                from pyworkflow.serialization.decoder import deserialize

                result = deserialize(child_run.result) if child_run.result else None
                logger.info(
                    f"[recovery] Child {child_id} already completed, using cached result",
                    run_id=ctx.run_id,
                    child_run_id=existing_child_run_id,
                )

                if wait_for_completion:
                    return result
                else:
                    return ChildWorkflowHandle(
                        child_id=child_id,
                        child_run_id=existing_child_run_id,
                        child_workflow_name=child_workflow_name,
                        parent_run_id=ctx.run_id,
                        _storage=storage,
                    )

            elif child_run.status == RunStatus.FAILED:
                # Child failed while we were recovering
                logger.info(
                    f"[recovery] Child {child_id} already failed",
                    run_id=ctx.run_id,
                    child_run_id=existing_child_run_id,
                )
                if wait_for_completion:
                    raise ChildWorkflowFailedError(
                        child_run_id=existing_child_run_id,
                        child_workflow_name=child_workflow_name,
                        error=child_run.error or "Unknown error",
                        error_type="ChildWorkflowError",
                    )
                else:
                    return ChildWorkflowHandle(
                        child_id=child_id,
                        child_run_id=existing_child_run_id,
                        child_workflow_name=child_workflow_name,
                        parent_run_id=ctx.run_id,
                        _storage=storage,
                    )

            elif child_run.status in (
                RunStatus.PENDING,
                RunStatus.RUNNING,
                RunStatus.SUSPENDED,
            ):
                # Child is still running - wait for it, don't start a new one
                logger.info(
                    f"[recovery] Child {child_id} still running, waiting for existing child",
                    run_id=ctx.run_id,
                    child_run_id=existing_child_run_id,
                    child_status=child_run.status.value,
                )

                if not wait_for_completion:
                    return ChildWorkflowHandle(
                        child_id=child_id,
                        child_run_id=existing_child_run_id,
                        child_workflow_name=child_workflow_name,
                        parent_run_id=ctx.run_id,
                        _storage=storage,
                    )

                # Suspend to wait for the existing child
                raise SuspensionSignal(
                    reason=f"child_workflow:{child_id}",
                    child_id=child_id,
                    child_run_id=existing_child_run_id,
                    child_workflow_name=child_workflow_name,
                )

    # Start the child workflow
    child_run_id = await _start_child_on_worker(
        ctx=ctx,
        storage=storage,
        child_id=child_id,
        workflow_meta=workflow_meta,
        args=args,
        kwargs=kwargs,
        wait_for_completion=wait_for_completion,
    )

    if not wait_for_completion:
        # Fire-and-forget: return handle immediately
        logger.info(
            f"Started child workflow (fire-and-forget): {child_workflow_name}",
            parent_run_id=ctx.run_id,
            child_run_id=child_run_id,
            child_id=child_id,
        )
        return ChildWorkflowHandle(
            child_id=child_id,
            child_run_id=child_run_id,
            child_workflow_name=child_workflow_name,
            parent_run_id=ctx.run_id,
            _storage=storage,
        )

    # Wait for completion: suspend parent
    logger.info(
        f"Started child workflow (waiting): {child_workflow_name}",
        parent_run_id=ctx.run_id,
        child_run_id=child_run_id,
        child_id=child_id,
    )

    # Raise suspension to wait for child
    raise SuspensionSignal(
        reason=f"child_workflow:{child_id}",
        child_id=child_id,
        child_run_id=child_run_id,
        child_workflow_name=child_workflow_name,
    )


def _generate_child_id(workflow_name: str, args: tuple, kwargs: dict) -> str:
    """
    Generate deterministic child ID based on workflow name and arguments.

    This ensures the same child workflow with the same arguments always
    gets the same ID, enabling proper replay behavior.
    """
    args_str = serialize_args(*args)
    kwargs_str = serialize_kwargs(**kwargs)
    content = f"child:{workflow_name}:{args_str}:{kwargs_str}"
    hash_hex = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"child_{workflow_name}_{hash_hex}"


async def _start_child_on_worker(
    ctx: Any,
    storage: Any,
    child_id: str,
    workflow_meta: "WorkflowMetadata",
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    wait_for_completion: bool,
) -> str:
    """
    Start child workflow execution and record events.

    This function:
    1. Generates a unique child run_id
    2. Records CHILD_WORKFLOW_STARTED event in parent's log
    3. Creates the child WorkflowRun record
    4. Schedules child execution (via runtime)
    """
    # Generate child run_id
    child_run_id = f"run_{uuid.uuid4().hex[:16]}"

    # Get parent's nesting depth
    parent_depth = await storage.get_nesting_depth(ctx.run_id)
    child_depth = parent_depth + 1

    # Serialize arguments
    args_json = serialize_args(*args)
    kwargs_json = serialize_kwargs(**kwargs)

    # Record CHILD_WORKFLOW_STARTED event in parent's log
    start_event = create_child_workflow_started_event(
        run_id=ctx.run_id,
        child_id=child_id,
        child_run_id=child_run_id,
        child_workflow_name=workflow_meta.name,
        args=args_json,
        kwargs=kwargs_json,
        wait_for_completion=wait_for_completion,
    )
    await storage.record_event(start_event)

    # Create child workflow run record
    child_run = WorkflowRun(
        run_id=child_run_id,
        workflow_name=workflow_meta.name,
        status=RunStatus.PENDING,
        created_at=datetime.now(UTC),
        input_args=args_json,
        input_kwargs=kwargs_json,
        parent_run_id=ctx.run_id,
        nesting_depth=child_depth,
        max_duration=workflow_meta.max_duration,
        context={},  # Step context
    )
    await storage.create_run(child_run)

    # Delegate child workflow execution to the runtime
    from pyworkflow.config import get_config
    from pyworkflow.runtime import get_runtime

    config = get_config()
    runtime = get_runtime(config.default_runtime)

    await runtime.start_child_workflow(
        workflow_func=workflow_meta.func,
        args=args,
        kwargs=kwargs,
        child_run_id=child_run_id,
        workflow_name=workflow_meta.name,
        storage=storage,
        parent_run_id=ctx.run_id,
        child_id=child_id,
        wait_for_completion=wait_for_completion,
    )

    return child_run_id
