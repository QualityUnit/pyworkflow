"""
@step decorator for defining workflow steps.

Steps are isolated, retryable units of work that:
- Execute actual business logic
- Have automatic retry on failure
- Cache results for replay
- Run independently (can be distributed)

Supports multiple runtimes:
- Local: In-process execution with optional event sourcing
- Celery: Distributed execution via Celery workers
- AWS: AWS Durable Lambda Functions with automatic checkpointing
"""

import functools
import hashlib
from collections.abc import Callable
from typing import Any

from loguru import logger

from pyworkflow.context import get_context, has_context
from pyworkflow.core.exceptions import FatalError, RetryableError
from pyworkflow.core.registry import register_step
from pyworkflow.engine.events import (
    create_step_completed_event,
    create_step_failed_event,
    create_step_started_event,
)
from pyworkflow.serialization.encoder import serialize, serialize_args, serialize_kwargs


def _get_aws_context() -> Any | None:
    """
    Get the current AWS workflow context if running in AWS environment.

    Returns None if not in AWS context or AWS module not available.
    """
    try:
        from pyworkflow.aws.context import get_aws_context

        return get_aws_context()
    except ImportError:
        # AWS module not installed
        return None


def step(
    name: str | None = None,
    max_retries: int = 3,
    retry_delay: str | int | list[int] = "exponential",
    timeout: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Callable:
    """
    Decorator to mark functions as workflow steps.

    Steps are isolated units of work with automatic retry and result caching.
    They can be called both within workflows and independently.

    Args:
        name: Optional step name (defaults to function name)
        max_retries: Maximum number of retry attempts (default: 3)
        retry_delay: Retry delay strategy:
            - "exponential": Exponential backoff (1s, 2s, 4s, 8s, ...)
            - int: Fixed delay in seconds
            - List[int]: Custom delays for each retry
        timeout: Optional timeout in seconds
        metadata: Optional metadata dictionary

    Returns:
        Decorated step function

    Examples:
        @step
        async def simple_step(x: int):
            return x * 2

        @step(max_retries=5, retry_delay=10)
        async def api_call(url: str):
            response = await httpx.get(url)
            return response.json()

        @step(retry_delay=[5, 30, 300])
        async def custom_retry_step():
            # Retries: after 5s, then 30s, then 300s
            pass
    """

    def decorator(func: Callable) -> Callable:
        step_name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Check if running in AWS Durable Lambda context
            aws_ctx = _get_aws_context()
            if aws_ctx is not None:
                logger.debug(f"Step {step_name} running in AWS context, delegating to AWS SDK")
                # Delegate to AWS context for checkpointed execution
                return aws_ctx.execute_step(func, *args, step_name=step_name, **kwargs)

            # Check if we're in a workflow context
            if not has_context():
                # Called outside workflow - execute directly
                logger.debug(f"Step {step_name} called outside workflow, executing directly")
                return await func(*args, **kwargs)

            ctx = get_context()

            # Check for cancellation before executing step
            ctx.check_cancellation()

            # Transient mode: execute directly without event sourcing
            # Retries are still supported via direct execution
            if not ctx.is_durable:
                logger.debug(
                    f"Step {step_name} in transient mode, executing directly",
                    run_id=ctx.run_id,
                )
                return await _execute_with_retries(
                    func, args, kwargs, step_name, max_retries, retry_delay
                )

            # Durable mode: use event sourcing
            # Generate step ID (deterministic based on name + args)
            step_id = _generate_step_id(step_name, args, kwargs)

            # Check if step has already completed (replay)
            if not ctx.should_execute_step(step_id):
                # Check if step failed (for distributed step dispatch)
                if ctx.has_step_failed(step_id):
                    error_info = ctx.get_step_failure(step_id)
                    logger.error(
                        f"Step {step_name} failed on remote worker",
                        run_id=ctx.run_id,
                        step_id=step_id,
                        error=error_info.get("error") if error_info else "Unknown error",
                    )
                    raise FatalError(
                        f"Step {step_name} failed: "
                        f"{error_info.get('error') if error_info else 'Unknown error'}"
                    )

                logger.debug(
                    f"Step {step_name} already completed, using cached result",
                    run_id=ctx.run_id,
                    step_id=step_id,
                )
                return ctx.get_step_result(step_id)

            # ========== Distributed Step Dispatch ==========
            # When running in a distributed runtime (e.g., Celery), dispatch steps
            # to step workers instead of executing inline.
            if ctx.runtime == "celery":
                return await _dispatch_step_to_celery(
                    ctx=ctx,
                    func=func,
                    args=args,
                    kwargs=kwargs,
                    step_name=step_name,
                    step_id=step_id,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    timeout=timeout,
                )

            # Check if we're resuming from a retry
            retry_state = ctx.get_retry_state(step_id)
            if retry_state:
                current_attempt = retry_state["current_attempt"]
                resume_at = retry_state.get("resume_at")

                # Check if retry delay has elapsed during replay
                if ctx.is_replaying and resume_at:
                    from datetime import UTC, datetime

                    now = datetime.now(UTC)
                    if now < resume_at:
                        # Not ready to retry yet - re-raise suspension
                        logger.debug(
                            f"Retry delay not elapsed for {step_name}, re-suspending",
                            run_id=ctx.run_id,
                            step_id=step_id,
                            current_attempt=current_attempt,
                            resume_at=resume_at.isoformat(),
                        )
                        from pyworkflow.core.exceptions import SuspensionSignal

                        raise SuspensionSignal(
                            reason=f"retry:{step_id}",
                            resume_at=resume_at,
                            step_id=step_id,
                            attempt=current_attempt,
                        )
            else:
                current_attempt = 1

            # Validate event limits before executing step
            await ctx.validate_event_limits()

            # Record step start event
            start_event = create_step_started_event(
                run_id=ctx.run_id,
                step_id=step_id,
                step_name=step_name,
                args=serialize_args(*args),
                kwargs=serialize_kwargs(**kwargs),
                attempt=current_attempt,
            )
            await ctx.storage.record_event(start_event)  # type: ignore[union-attr]

            logger.info(
                f"Executing step: {step_name} (attempt {current_attempt}/{max_retries + 1})",
                run_id=ctx.run_id,
                step_id=step_id,
                step_name=step_name,
                attempt=current_attempt,
            )

            # Check for cancellation before executing step
            ctx.check_cancellation()

            try:
                # Execute step function
                result = await func(*args, **kwargs)

                # Record completion event
                completion_event = create_step_completed_event(
                    run_id=ctx.run_id,
                    step_id=step_id,
                    result=serialize(result),
                    step_name=step_name,
                )
                await ctx.storage.record_event(completion_event)  # type: ignore[union-attr]

                # Cache result for replay
                ctx.cache_step_result(step_id, result)

                # Clear retry state on success
                ctx.clear_retry_state(step_id)

                logger.info(
                    f"Step completed: {step_name}",
                    run_id=ctx.run_id,
                    step_id=step_id,
                )

                return result

            except FatalError as e:
                # Fatal error - don't retry
                logger.error(
                    f"Step failed (fatal): {step_name}",
                    run_id=ctx.run_id,
                    step_id=step_id,
                    error=str(e),
                )

                # Record failure event
                failure_event = create_step_failed_event(
                    run_id=ctx.run_id,
                    step_id=step_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    is_retryable=False,
                    attempt=current_attempt,
                )
                await ctx.storage.record_event(failure_event)  # type: ignore[union-attr]

                # Clear retry state
                ctx.clear_retry_state(step_id)

                raise

            except (RetryableError, Exception) as e:
                # Handle retriable errors (RetryableError or generic Exception)
                # FatalError is already handled above
                is_retryable_error = isinstance(e, RetryableError)

                # Check if we have retries left
                if current_attempt <= max_retries:
                    # We can retry
                    next_attempt = current_attempt + 1

                    # Calculate retry delay
                    delay_seconds: float
                    if isinstance(e, RetryableError) and e.retry_after is not None:
                        # Use RetryableError's specified delay
                        delay_seconds = float(e.get_retry_delay_seconds() or 0)
                    else:
                        # Use step's configured retry delay strategy
                        delay_seconds = _get_retry_delay(retry_delay, current_attempt - 1)

                    # Calculate resume time
                    from datetime import UTC, datetime, timedelta

                    resume_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)

                    logger.warning(
                        f"Step failed (retriable): {step_name}, "
                        f"retrying in {delay_seconds}s (attempt {next_attempt}/{max_retries + 1})",
                        run_id=ctx.run_id,
                        step_id=step_id,
                        error=str(e),
                        current_attempt=current_attempt,
                        next_attempt=next_attempt,
                    )

                    # Record STEP_FAILED event
                    failure_event = create_step_failed_event(
                        run_id=ctx.run_id,
                        step_id=step_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        is_retryable=True,
                        attempt=current_attempt,
                    )
                    await ctx.storage.record_event(failure_event)  # type: ignore[union-attr]

                    # Record STEP_RETRYING event
                    from pyworkflow.engine.events import create_step_retrying_event

                    retrying_event = create_step_retrying_event(
                        run_id=ctx.run_id,
                        step_id=step_id,
                        attempt=next_attempt,
                        retry_after=str(int(delay_seconds)),
                        error=str(e),
                    )
                    # Add additional fields to event data
                    retrying_event.data["resume_at"] = resume_at.isoformat()
                    retrying_event.data["retry_strategy"] = str(retry_delay)
                    retrying_event.data["max_retries"] = max_retries
                    await ctx.storage.record_event(retrying_event)  # type: ignore[union-attr]

                    # Update retry state in context
                    ctx.set_retry_state(
                        step_id=step_id,
                        attempt=next_attempt,
                        resume_at=resume_at,
                        max_retries=max_retries,
                        retry_delay=retry_delay,
                        last_error=str(e),
                    )

                    # Raise suspension signal to pause workflow
                    # Note: The workflow-level exception handler will schedule automatic resumption
                    from pyworkflow.core.exceptions import SuspensionSignal

                    raise SuspensionSignal(
                        reason=f"retry:{step_id}",
                        resume_at=resume_at,
                        step_id=step_id,
                        attempt=next_attempt,
                    )

                else:
                    # Max retries exhausted
                    logger.error(
                        f"Step failed after {max_retries + 1} attempts: {step_name}",
                        run_id=ctx.run_id,
                        step_id=step_id,
                        error=str(e),
                        total_attempts=current_attempt,
                    )

                    # Record final STEP_FAILED event
                    failure_event = create_step_failed_event(
                        run_id=ctx.run_id,
                        step_id=step_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        is_retryable=True,
                        attempt=current_attempt,
                    )
                    await ctx.storage.record_event(failure_event)  # type: ignore[union-attr]

                    ctx.clear_retry_state(step_id)

                    # Convert to RetryableError if it wasn't already
                    if not is_retryable_error:
                        raise RetryableError(
                            f"Step {step_name} failed after {max_retries + 1} attempts: {e}"
                        ) from e
                    else:
                        raise

        # Register step
        register_step(
            name=step_name,
            func=wrapper,
            original_func=func,
            max_retries=max_retries,
            retry_delay=str(retry_delay),
            timeout=timeout,
            metadata=metadata,
        )

        # Store metadata on wrapper
        wrapper.__step__ = True  # type: ignore[attr-defined]
        wrapper.__step_name__ = step_name  # type: ignore[attr-defined]
        wrapper.__step_max_retries__ = max_retries  # type: ignore[attr-defined]
        wrapper.__step_retry_delay__ = retry_delay  # type: ignore[attr-defined]
        wrapper.__step_timeout__ = timeout  # type: ignore[attr-defined]
        wrapper.__step_metadata__ = metadata or {}  # type: ignore[attr-defined]

        return wrapper

    return decorator


async def _execute_with_retries(
    func: Callable,
    args: tuple,
    kwargs: dict,
    step_name: str,
    max_retries: int,
    retry_delay: str | int | list[int],
) -> Any:
    """
    Execute a step function with retry logic (for transient mode).

    Args:
        func: The step function to execute
        args: Positional arguments
        kwargs: Keyword arguments
        step_name: Name of the step for logging
        max_retries: Maximum number of retry attempts
        retry_delay: Retry delay strategy

    Returns:
        Result of the function

    Raises:
        Exception: If all retries exhausted
    """
    import asyncio

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)

        except FatalError:
            # Fatal errors are not retried
            raise

        except Exception as e:
            last_error = e

            if attempt < max_retries:
                # Calculate delay
                delay = _get_retry_delay(retry_delay, attempt)

                logger.warning(
                    f"Step {step_name} failed (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {delay}s",
                    error=str(e),
                )

                await asyncio.sleep(delay)
            else:
                # All retries exhausted
                logger.error(
                    f"Step {step_name} failed after {max_retries + 1} attempts",
                    error=str(e),
                )

    assert last_error is not None  # mypy: guaranteed by loop logic
    raise last_error


def _get_retry_delay(retry_delay: str | int | list[int], attempt: int) -> float:
    """
    Calculate retry delay based on strategy.

    Args:
        retry_delay: Delay strategy ("exponential", int, or list)
        attempt: Current attempt number (0-indexed)

    Returns:
        Delay in seconds
    """
    if retry_delay == "exponential":
        # Exponential backoff: 1, 2, 4, 8, 16, ... (capped at 300s)
        return min(2**attempt, 300)
    elif isinstance(retry_delay, int):
        return retry_delay
    elif isinstance(retry_delay, list):
        # Use custom delays, fall back to last value if out of range
        if attempt < len(retry_delay):
            return retry_delay[attempt]
        return retry_delay[-1] if retry_delay else 1
    else:
        # Default to 1 second
        return 1


def _generate_step_id(step_name: str, args: tuple, kwargs: dict) -> str:
    """
    Generate deterministic step ID based on name and arguments.

    This ensures the same step with same arguments always gets the same ID,
    enabling proper replay behavior.

    Args:
        step_name: Step name
        args: Positional arguments
        kwargs: Keyword arguments

    Returns:
        Deterministic step ID
    """
    # Serialize arguments
    args_str = serialize_args(*args)
    kwargs_str = serialize_kwargs(**kwargs)

    # Create hash of step name + arguments
    content = f"{step_name}:{args_str}:{kwargs_str}"
    hash_hex = hashlib.sha256(content.encode()).hexdigest()[:16]

    return f"step_{step_name}_{hash_hex}"


async def _dispatch_step_to_celery(
    ctx: Any,  # WorkflowContext
    func: Callable,
    args: tuple,
    kwargs: dict,
    step_name: str,
    step_id: str,
    max_retries: int,
    retry_delay: str | int | list[int],
    timeout: int | None,
) -> Any:
    """
    Dispatch step execution to Celery step worker.

    Instead of executing the step inline, this function:
    1. Records STEP_STARTED event
    2. Dispatches the step to execute_step_task on the steps queue
    3. Raises SuspensionSignal to pause the workflow

    The step worker will:
    1. Execute the step function
    2. Record STEP_COMPLETED/STEP_FAILED event
    3. Trigger workflow resumption

    Args:
        ctx: Workflow context
        func: Step function to execute
        args: Positional arguments
        kwargs: Keyword arguments
        step_name: Name of the step
        step_id: Deterministic step ID
        max_retries: Maximum retry attempts
        retry_delay: Retry delay strategy
        timeout: Optional timeout in seconds

    Returns:
        This function never returns normally - it always raises SuspensionSignal

    Raises:
        SuspensionSignal: To pause workflow while step executes on worker
    """
    from pyworkflow.celery.tasks import execute_step_task
    from pyworkflow.core.exceptions import SuspensionSignal

    logger.info(
        f"Dispatching step to Celery worker: {step_name}",
        run_id=ctx.run_id,
        step_id=step_id,
    )

    # Validate event limits before recording step event
    await ctx.validate_event_limits()

    # Record STEP_STARTED event
    start_event = create_step_started_event(
        run_id=ctx.run_id,
        step_id=step_id,
        step_name=step_name,
        args=serialize_args(*args),
        kwargs=serialize_kwargs(**kwargs),
        attempt=1,
    )
    await ctx.storage.record_event(start_event)

    # Serialize arguments for Celery transport
    args_json = serialize_args(*args)
    kwargs_json = serialize_kwargs(**kwargs)

    # Get step context data if available
    context_data = None
    context_class_name = None
    try:
        from pyworkflow.context.step_context import get_step_context, has_step_context

        if has_step_context():
            step_ctx = get_step_context()
            context_data = step_ctx.to_dict()
            context_class_name = f"{step_ctx.__class__.__module__}.{step_ctx.__class__.__name__}"
    except Exception:
        pass  # Step context not available

    # Dispatch to Celery step queue
    task_result = execute_step_task.delay(
        step_name=step_name,
        args_json=args_json,
        kwargs_json=kwargs_json,
        run_id=ctx.run_id,
        step_id=step_id,
        max_retries=max_retries,
        storage_config=ctx.storage_config,
        context_data=context_data,
        context_class_name=context_class_name,
    )

    logger.info(
        f"Step dispatched to Celery: {step_name}",
        run_id=ctx.run_id,
        step_id=step_id,
        task_id=task_result.id,
    )

    # Raise suspension signal - workflow will pause until step completes
    # The step worker will record STEP_COMPLETED and trigger resume
    raise SuspensionSignal(
        reason=f"step_dispatch:{step_id}",
        step_id=step_id,
        step_name=step_name,
        task_id=task_result.id,
    )
