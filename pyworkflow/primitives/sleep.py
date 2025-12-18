"""
Sleep primitive for workflow delays.

Allows workflows to pause execution for a specified duration without
holding resources. The workflow will suspend and can be resumed after
the delay period.
"""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Optional, Union

from loguru import logger

from pyworkflow.context import get_context, has_context
from pyworkflow.utils.duration import parse_duration


async def sleep(
    duration: Union[str, int, float, timedelta, datetime],
    name: Optional[str] = None,
) -> None:
    """
    Suspend workflow execution for a specified duration.

    This function checks for context in two ways:
    1. New context API (pyworkflow.context) - for ctx.run()/ctx.sleep() pattern
    2. Old context API (pyworkflow.core.context) - for @workflow/@step pattern

    Different contexts handle sleep differently:
    - MockContext: Skips sleep (configurable)
    - LocalContext: Durable sleep with event sourcing
    - AWSContext: AWS native wait (no compute charges)

    If called outside a workflow context, falls back to asyncio.sleep.

    Args:
        duration: How long to sleep:
            - str: Duration string ("5s", "2m", "1h", "3d", "1w")
            - int/float: Seconds
            - timedelta: Time duration
            - datetime: Sleep until this specific time
        name: Optional name for this sleep (for debugging)

    Examples:
        # Sleep for 30 seconds
        await sleep("30s")

        # Sleep for 5 minutes
        await sleep("5m")
        await sleep(300)  # Same as above

        # Sleep for 1 hour
        await sleep("1h")
        await sleep(timedelta(hours=1))

        # Named sleep for debugging
        await sleep("5m", name="wait_for_rate_limit")
    """
    # Check for new context API first
    if has_context():
        ctx = get_context()
        duration_seconds = _calculate_delay_seconds(duration)

        logger.debug(
            f"Sleep {duration_seconds}s via {ctx.__class__.__name__}",
            run_id=ctx.run_id,
            workflow_name=ctx.workflow_name,
        )

        await ctx.sleep(duration_seconds)
        return

    # Check for old context API (backward compatibility)
    from pyworkflow.core.context import has_current_context, get_current_context

    if has_current_context():
        # Use the old durable sleep implementation
        await _durable_sleep_old_api(duration, name)
        return

    # No context available - use regular asyncio.sleep
    duration_seconds = _calculate_delay_seconds(duration)
    logger.debug(
        f"Sleep called outside workflow context, using asyncio.sleep for {duration_seconds}s"
    )
    await asyncio.sleep(duration_seconds)


async def _durable_sleep_old_api(
    duration: Union[str, int, float, timedelta, datetime],
    name: Optional[str] = None,
) -> None:
    """
    Durable sleep implementation for the old context API.

    This handles sleep with event sourcing when using @workflow/@step decorators.
    """
    from pyworkflow.core.context import get_current_context
    from pyworkflow.core.exceptions import SuspensionSignal
    from pyworkflow.engine.events import create_sleep_started_event

    ctx = get_current_context()

    # Transient mode: use regular asyncio.sleep
    if not ctx.is_durable():
        delay_seconds = _calculate_delay_seconds(duration)
        logger.debug(
            f"Sleep in transient mode, using asyncio.sleep for {delay_seconds}s",
            run_id=ctx.run_id,
        )
        await asyncio.sleep(delay_seconds)
        return

    # Durable mode: use durable sleep with event sourcing
    sleep_id = _generate_sleep_id(name, ctx.run_id)

    # Check if sleep has already completed (replay)
    if not ctx.should_execute_sleep(sleep_id):
        logger.debug(
            f"Sleep {sleep_id} already completed during replay",
            run_id=ctx.run_id,
            sleep_id=sleep_id,
        )
        return

    # Check if we're resuming from this sleep (it's in pending_sleeps from event replay)
    if sleep_id in ctx.pending_sleeps:
        # Get the original resume_at from event replay
        resume_at = ctx.pending_sleeps[sleep_id]
        now = datetime.now(UTC)

        if now >= resume_at:
            # Sleep duration has elapsed - mark as completed and continue
            ctx.mark_sleep_completed(sleep_id)
            logger.debug(
                f"Sleep {sleep_id} duration elapsed during resume",
                run_id=ctx.run_id,
                sleep_id=sleep_id,
                resume_at=resume_at.isoformat(),
                now=now.isoformat(),
            )
            return
        else:
            # Not enough time has passed - re-raise suspension
            logger.debug(
                f"Sleep {sleep_id} not ready yet, re-suspending",
                run_id=ctx.run_id,
                sleep_id=sleep_id,
                resume_at=resume_at.isoformat(),
                now=now.isoformat(),
            )
            from pyworkflow.core.exceptions import SuspensionSignal

            raise SuspensionSignal(
                reason=f"sleep:{sleep_id}",
                resume_at=resume_at,
                sleep_id=sleep_id,
            )

    # First time encountering this sleep - calculate resume time
    resume_at = _calculate_resume_time(duration)
    delay_seconds = _calculate_delay_seconds(duration)

    # Record sleep start event
    start_event = create_sleep_started_event(
        run_id=ctx.run_id,
        sleep_id=sleep_id,
        duration_seconds=delay_seconds,
        resume_at=resume_at,
        name=name,
    )
    await ctx.storage.record_event(start_event)

    logger.info(
        f"Workflow sleeping for {delay_seconds}s",
        run_id=ctx.run_id,
        sleep_id=sleep_id,
        duration_seconds=delay_seconds,
        resume_at=resume_at.isoformat(),
        name=name,
    )

    # Add to pending sleeps
    ctx.add_pending_sleep(sleep_id, resume_at)

    # Schedule automatic resumption with Celery (if available)
    # Skip if Celery not configured to avoid broker connection attempts
    try:
        from pyworkflow.config import get_config

        config = get_config()
        if config.celery_broker:
            from pyworkflow.celery.tasks import schedule_workflow_resumption

            schedule_workflow_resumption(ctx.run_id, resume_at)
            logger.info(
                f"Scheduled automatic workflow resumption",
                run_id=ctx.run_id,
                resume_at=resume_at.isoformat(),
            )
        else:
            logger.debug(
                f"Celery broker not configured, skipping automatic resumption (use manual resume())",
                run_id=ctx.run_id,
            )
    except (ImportError, AttributeError, Exception) as e:
        logger.debug(
            f"Could not schedule automatic resumption: {e}",
            run_id=ctx.run_id,
        )

    # Raise suspension signal to pause workflow
    raise SuspensionSignal(
        reason=f"sleep:{sleep_id}",
        resume_at=resume_at,
        sleep_id=sleep_id,
    )


def _generate_sleep_id(name: Optional[str], run_id: str) -> str:
    """
    Generate deterministic sleep ID.

    Uses name if provided, otherwise generates based on call location in source code.
    This ensures the same sleep always gets the same ID during replay.
    """
    import inspect

    if name:
        # Use provided name (deterministic)
        content = f"{run_id}:{name}"
        hash_hex = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"sleep_{name}_{hash_hex}"
    else:
        # Generate based on the call location (file + line number)
        # This makes it deterministic - same line always gets same ID
        frame = inspect.currentframe()
        try:
            # Walk up the stack to find the caller (skip internal functions)
            caller_frame = frame.f_back.f_back.f_back  # sleep() -> _durable_sleep_old_api() -> caller
            filename = caller_frame.f_code.co_filename
            lineno = caller_frame.f_lineno
            func_name = caller_frame.f_code.co_name

            # Create deterministic ID from call location
            content = f"{filename}:{func_name}:{lineno}"
            hash_hex = hashlib.sha256(content.encode()).hexdigest()[:16]
            return f"sleep_{hash_hex}"
        finally:
            del frame  # Avoid reference cycles


def _calculate_resume_time(duration: Union[str, int, float, timedelta, datetime]) -> datetime:
    """Calculate when the sleep should resume."""
    if isinstance(duration, datetime):
        return duration

    delay_seconds = _calculate_delay_seconds(duration)
    return datetime.now(UTC) + timedelta(seconds=delay_seconds)


def _calculate_delay_seconds(duration: Union[str, int, float, timedelta, datetime]) -> int:
    """Calculate delay in seconds."""
    if isinstance(duration, datetime):
        now = datetime.now(UTC)
        if duration <= now:
            raise ValueError(f"Cannot sleep until past time: {duration} (now: {now})")
        delta = duration - now
        return int(delta.total_seconds())

    if isinstance(duration, timedelta):
        return int(duration.total_seconds())
    elif isinstance(duration, str):
        return parse_duration(duration)
    else:
        return int(duration)
