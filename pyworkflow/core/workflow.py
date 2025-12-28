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
from collections.abc import Callable
from typing import Any

from loguru import logger

from pyworkflow.context import LocalContext, reset_context, set_context
from pyworkflow.core.exceptions import CancellationError, ContinueAsNewSignal, SuspensionSignal
from pyworkflow.core.registry import register_workflow
from pyworkflow.engine.events import (
    create_workflow_cancelled_event,
    create_workflow_completed_event,
    create_workflow_failed_event,
)
from pyworkflow.serialization.encoder import serialize


def workflow(
    name: str | None = None,
    durable: bool | None = None,
    max_duration: str | None = None,
    tags: list[str] | None = None,
    recover_on_worker_loss: bool | None = None,
    max_recovery_attempts: int | None = None,
    context_class: type | None = None,
) -> Callable:
    """
    Decorator to mark async functions as workflows.

    Workflows are orchestration functions that coordinate steps. They can be:
    - Durable: Event-sourced, persistent, resumable (durable=True)
    - Transient: Simple execution without persistence overhead (durable=False)

    Args:
        name: Optional workflow name (defaults to function name)
        durable: Whether workflow is durable (None = use configured default)
        max_duration: Optional max duration (e.g., "1h", "30m")
        tags: Optional list of tags for categorization (max 3 tags)
        recover_on_worker_loss: Whether to auto-recover on worker failure
            (None = True for durable, False for transient)
        max_recovery_attempts: Max recovery attempts on worker failure (default: 3)
        context_class: Optional StepContext subclass for step context access.
            When provided, enables get_step_context() and set_step_context()
            for passing context data to steps running on remote workers.

    Returns:
        Decorated workflow function

    Example (durable):
        @workflow(name="process_order", durable=True)
        async def process_order(order_id: str):
            order = await validate_order(order_id)
            payment = await charge_payment(order["total"])
            await sleep("1h")  # Can suspend and resume
            return payment

    Example (transient):
        @workflow(durable=False)
        async def quick_task():
            result = await my_step()
            return result

    Example (use configured default):
        @workflow
        async def simple_workflow():
            result = await my_step()
            return result

    Example (fault tolerant):
        @workflow(durable=True, recover_on_worker_loss=True, max_recovery_attempts=5)
        async def critical_workflow():
            # Will auto-recover if worker crashes
            result = await important_step()
            return result

    Example (with tags):
        @workflow(tags=["backend", "critical"])
        async def tagged_workflow():
            result = await my_step()
            return result

    Example (with step context):
        class OrderContext(StepContext):
            workspace_id: str = ""
            user_id: str = ""

        @workflow(context_class=OrderContext)
        async def workflow_with_context():
            ctx = OrderContext(workspace_id="ws-123")
            set_step_context(ctx)  # Persisted and available in steps
            result = await my_step()  # Step can call get_step_context()
            return result
    """

    # Validate tags
    validated_tags = tags or []
    if len(validated_tags) > 3:
        raise ValueError(
            f"Workflows can have at most 3 tags, got {len(validated_tags)}: {validated_tags}"
        )

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
            tags=validated_tags,
            context_class=context_class,
        )

        # Store metadata on wrapper
        wrapper.__workflow__ = True  # type: ignore[attr-defined]
        wrapper.__workflow_name__ = workflow_name  # type: ignore[attr-defined]
        wrapper.__workflow_durable__ = durable  # type: ignore[attr-defined]  # None = use config default
        wrapper.__workflow_max_duration__ = max_duration  # type: ignore[attr-defined]
        wrapper.__workflow_tags__ = validated_tags  # type: ignore[attr-defined]
        wrapper.__workflow_recover_on_worker_loss__ = (  # type: ignore[attr-defined]
            recover_on_worker_loss  # None = use config default
        )
        wrapper.__workflow_max_recovery_attempts__ = (  # type: ignore[attr-defined]
            max_recovery_attempts  # None = use config default
        )
        wrapper.__workflow_context_class__ = context_class  # type: ignore[attr-defined]

        return wrapper

    return decorator


async def execute_workflow_with_context(
    workflow_func: Callable,
    run_id: str,
    workflow_name: str,
    storage: Any,  # StorageBackend or None for transient
    args: tuple,
    kwargs: dict,
    event_log: list | None = None,
    durable: bool = True,
    cancellation_requested: bool = False,
    runtime: str | None = None,
    storage_config: dict | None = None,
) -> Any:
    """
    Execute workflow function with proper context setup.

    This is called by the executor to run a workflow with:
    - Context initialization
    - Event logging (durable mode only)
    - Error handling
    - Suspension handling (durable mode only)
    - Cancellation handling

    Args:
        workflow_func: The workflow function to execute
        run_id: Unique run identifier
        workflow_name: Workflow name
        storage: Storage backend instance (None for transient)
        args: Positional arguments
        kwargs: Keyword arguments
        event_log: Optional existing event log for replay
        durable: Whether this is a durable workflow
        cancellation_requested: Whether cancellation was requested before execution
        runtime: Runtime environment slug (e.g., "celery") for distributed step dispatch
        storage_config: Storage configuration dict for distributed step workers

    Returns:
        Workflow result

    Raises:
        SuspensionSignal: When workflow needs to suspend (durable only)
        CancellationError: When workflow is cancelled
        Exception: On workflow failure
    """
    # Determine if we're actually durable (need both flag and storage)
    is_durable = durable and storage is not None

    # Create workflow context using new LocalContext
    ctx = LocalContext(
        run_id=run_id,
        workflow_name=workflow_name,
        storage=storage,
        event_log=event_log or [],
        durable=is_durable,
    )

    # Set runtime environment for distributed step dispatch
    ctx._runtime = runtime
    ctx._storage_config = storage_config

    # Set cancellation state if requested before execution
    if cancellation_requested:
        ctx.request_cancellation(reason="Cancellation requested before execution")

    # Set as current context using new API
    token = set_context(ctx)

    # Set up step context if workflow has a context_class
    step_context_token = None
    step_context_class_token = None
    context_class = getattr(workflow_func, "__workflow_context_class__", None)
    if context_class is not None:
        from pyworkflow.context.step_context import (
            _set_step_context_class,
            _set_step_context_internal,
        )

        # Store context class for deserialization
        step_context_class_token = _set_step_context_class(context_class)

        # Load existing context from storage (for resumption)
        if is_durable and storage is not None:
            context_data = await storage.get_run_context(run_id)
            if context_data:
                step_ctx = context_class.from_dict(context_data)
                step_context_token = _set_step_context_internal(step_ctx)

    try:
        # Note: Event replay is handled by LocalContext in its constructor
        # when event_log is provided

        logger.info(
            f"Executing workflow: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            durable=is_durable,
            is_replay=bool(event_log),
        )

        # Execute workflow function
        result = await workflow_func(*args, **kwargs)

        # Record completion event (durable mode only)
        if is_durable:
            # Validate event limits before recording completion
            await ctx.validate_event_limits()

            completion_event = create_workflow_completed_event(
                run_id, serialize(result), workflow_name
            )
            await storage.record_event(completion_event)

        logger.info(
            f"Workflow completed: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            durable=is_durable,
        )

        return result

    except SuspensionSignal as e:
        # Workflow suspended (sleep/hook) - only happens in durable mode
        logger.info(
            f"Workflow suspended: {e.reason}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )
        raise

    except ContinueAsNewSignal as e:
        # Workflow continuing as new execution
        logger.info(
            f"Workflow continuing as new: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            new_args=e.workflow_args,
            new_kwargs=e.workflow_kwargs,
        )
        # Re-raise for caller (executor) to handle continuation
        raise

    except CancellationError as e:
        # Workflow was cancelled
        logger.info(
            f"Workflow cancelled: {workflow_name}",
            run_id=run_id,
            workflow_name=workflow_name,
            reason=e.reason,
        )

        # Record cancellation event (durable mode only)
        if is_durable:
            cancelled_event = create_workflow_cancelled_event(
                run_id=run_id,
                reason=e.reason,
                cleanup_completed=True,
            )
            await storage.record_event(cancelled_event)

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

        # Record failure event (durable mode only)
        if is_durable:
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
        # Clear step context if it was set
        if step_context_token is not None:
            from pyworkflow.context.step_context import _reset_step_context

            _reset_step_context(step_context_token)
        if step_context_class_token is not None:
            from pyworkflow.context.step_context import _reset_step_context_class

            _reset_step_context_class(step_context_class_token)

        # Clear context using new API
        reset_context(token)
