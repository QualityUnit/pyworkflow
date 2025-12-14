"""
@step decorator for defining workflow steps.

Steps are isolated, retryable units of work that:
- Execute actual business logic
- Have automatic retry on failure
- Cache results for replay
- Run independently (can be distributed)
"""

import functools
import hashlib
import uuid
from typing import Any, Callable, Dict, List, Optional, Union

from loguru import logger

from pyworkflow.core.context import get_current_context, has_current_context
from pyworkflow.core.exceptions import FatalError, RetryableError
from pyworkflow.core.registry import register_step
from pyworkflow.engine.events import (
    create_step_completed_event,
    create_step_failed_event,
    create_step_started_event,
)
from pyworkflow.serialization.decoder import deserialize
from pyworkflow.serialization.encoder import serialize, serialize_args, serialize_kwargs


def step(
    name: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: Union[str, int, List[int]] = "exponential",
    timeout: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
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
            # Check if we're in a workflow context
            if not has_current_context():
                # Called outside workflow - execute directly
                logger.debug(
                    f"Step {step_name} called outside workflow, executing directly"
                )
                return await func(*args, **kwargs)

            ctx = get_current_context()

            # Transient mode: execute directly without event sourcing
            # Retries are still supported via direct execution
            if not ctx.is_durable():
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
                logger.debug(
                    f"Step {step_name} already completed, using cached result",
                    run_id=ctx.run_id,
                    step_id=step_id,
                )
                return ctx.get_step_result(step_id)

            # Record step start event
            start_event = create_step_started_event(
                run_id=ctx.run_id,
                step_id=step_id,
                step_name=step_name,
                args=serialize_args(*args),
                kwargs=serialize_kwargs(**kwargs),
                attempt=1,
            )
            await ctx.storage.record_event(start_event)

            logger.info(
                f"Executing step: {step_name}",
                run_id=ctx.run_id,
                step_id=step_id,
                step_name=step_name,
            )

            try:
                # Execute step function
                result = await func(*args, **kwargs)

                # Record completion event
                completion_event = create_step_completed_event(
                    run_id=ctx.run_id, step_id=step_id, result=serialize(result)
                )
                await ctx.storage.record_event(completion_event)

                # Cache result for replay
                ctx.cache_step_result(step_id, result)

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
                    attempt=1,
                )
                await ctx.storage.record_event(failure_event)

                raise

            except RetryableError as e:
                # Retriable error - log and raise (will be handled by executor)
                logger.warning(
                    f"Step failed (retriable): {step_name}",
                    run_id=ctx.run_id,
                    step_id=step_id,
                    error=str(e),
                    retry_after=e.retry_after,
                )

                # Record failure event
                failure_event = create_step_failed_event(
                    run_id=ctx.run_id,
                    step_id=step_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    is_retryable=True,
                    attempt=1,
                )
                await ctx.storage.record_event(failure_event)

                raise

            except Exception as e:
                # Unexpected error - treat as retriable by default
                logger.error(
                    f"Step failed (unexpected): {step_name}",
                    run_id=ctx.run_id,
                    step_id=step_id,
                    error=str(e),
                    exc_info=True,
                )

                # Record failure event
                failure_event = create_step_failed_event(
                    run_id=ctx.run_id,
                    step_id=step_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    is_retryable=True,
                    attempt=1,
                )
                await ctx.storage.record_event(failure_event)

                # Convert to RetryableError for retry handling
                raise RetryableError(f"Step {step_name} failed: {e}") from e

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
        wrapper.__step__ = True
        wrapper.__step_name__ = step_name
        wrapper.__step_max_retries__ = max_retries
        wrapper.__step_retry_delay__ = retry_delay
        wrapper.__step_timeout__ = timeout
        wrapper.__step_metadata__ = metadata or {}

        return wrapper

    return decorator


async def _execute_with_retries(
    func: Callable,
    args: tuple,
    kwargs: dict,
    step_name: str,
    max_retries: int,
    retry_delay: Union[str, int, List[int]],
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

    last_error = None

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

    raise last_error


def _get_retry_delay(retry_delay: Union[str, int, List[int]], attempt: int) -> float:
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
