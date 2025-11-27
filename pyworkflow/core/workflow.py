"""
@workflow decorator for defining durable workflows.

Workflows are orchestration functions that coordinate steps. They are
decorated with @workflow to enable:
- Event sourcing and deterministic replay
- Suspension and resumption (sleep, hooks)
- Automatic state persistence
- Fault tolerance
"""

import functools
import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Dict, Optional

from loguru import logger

from pyworkflow.core.context import WorkflowContext, set_current_context
from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.core.registry import register_workflow
from pyworkflow.engine.events import (
    create_workflow_completed_event,
    create_workflow_failed_event,
    create_workflow_started_event,
)
from pyworkflow.serialization.encoder import serialize, serialize_args, serialize_kwargs


def workflow(
    name: Optional[str] = None,
    max_duration: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Callable:
    """
    Decorator to mark async functions as durable workflows.

    Workflows are orchestration functions that coordinate steps and maintain
    state through event sourcing. They can suspend (sleep/hooks) and resume
    without losing progress.

    Args:
        name: Optional workflow name (defaults to function name)
        max_duration: Optional max duration (e.g., "1h", "30m")
        metadata: Optional metadata dictionary

    Returns:
        Decorated workflow function

    Example:
        @workflow(name="process_order", max_duration="1h")
        async def process_order(order_id: str):
            order = await validate_order(order_id)
            payment = await charge_payment(order["total"])
            return payment

    Example (minimal):
        @workflow
        async def simple_workflow():
            result = await my_step()
            return result
    """

    def decorator(func: Callable) -> Callable:
        workflow_name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # This wrapper is called during execution by the executor
            # The actual workflow function runs with a context set up
            return await func(*args, **kwargs)

        # Register workflow
        register_workflow(
            name=workflow_name,
            func=wrapper,
            original_func=func,
            max_duration=max_duration,
            metadata=metadata,
        )

        # Store metadata on wrapper
        wrapper.__workflow__ = True
        wrapper.__workflow_name__ = workflow_name
        wrapper.__workflow_max_duration__ = max_duration
        wrapper.__workflow_metadata__ = metadata or {}

        return wrapper

    return decorator


async def execute_workflow_with_context(
    workflow_func: Callable,
    run_id: str,
    workflow_name: str,
    storage: Any,  # StorageBackend
    args: tuple,
    kwargs: dict,
    event_log: Optional[list] = None,
) -> Any:
    """
    Execute workflow function with proper context setup.

    This is called by the executor to run a workflow with:
    - Context initialization
    - Event logging
    - Error handling
    - Suspension handling

    Args:
        workflow_func: The workflow function to execute
        run_id: Unique run identifier
        workflow_name: Workflow name
        storage: Storage backend instance
        args: Positional arguments
        kwargs: Keyword arguments
        event_log: Optional existing event log for replay

    Returns:
        Workflow result

    Raises:
        SuspensionSignal: When workflow needs to suspend
        Exception: On workflow failure
    """
    # Create workflow context
    ctx = WorkflowContext(
        run_id=run_id,
        workflow_name=workflow_name,
        storage=storage,
        event_log=event_log or [],
        started_at=datetime.now(UTC),
    )

    # Set as current context
    set_current_context(ctx)

    try:
        # Replay events if resuming
        if event_log:
            from pyworkflow.engine.replay import replay_events

            await replay_events(ctx, event_log)

        logger.info(
            f"Executing workflow: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            is_replay=bool(event_log),
        )

        # Execute workflow function
        result = await workflow_func(*args, **kwargs)

        # Record completion event
        completion_event = create_workflow_completed_event(run_id, serialize(result))
        await storage.record_event(completion_event)

        logger.info(
            f"Workflow completed: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
        )

        return result

    except SuspensionSignal as e:
        # Workflow suspended (sleep/hook)
        logger.info(
            f"Workflow suspended: {e.reason}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )
        raise

    except Exception as e:
        # Workflow failed
        logger.error(
            f"Workflow failed: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            error=str(e),
            exc_info=True,
        )

        # Record failure event
        import traceback

        failure_event = create_workflow_failed_event(
            run_id=run_id,
            error=str(e),
            error_type=type(e).__name__,
            traceback=traceback.format_exc(),
        )
        await storage.record_event(failure_event)

        raise

    finally:
        # Clear context
        set_current_context(None)
