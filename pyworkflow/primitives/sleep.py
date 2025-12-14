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
    resume_at = _calculate_resume_time(duration)
    delay_seconds = _calculate_delay_seconds(duration)

    # Check if sleep has already completed (replay)
    if not ctx.should_execute_sleep(sleep_id):
        logger.debug(
            f"Sleep {sleep_id} already completed during replay",
            run_id=ctx.run_id,
            sleep_id=sleep_id,
        )
        return

    # Check if we're resuming and enough time has passed
    if ctx.is_replaying:
        now = datetime.now(UTC)
        if now >= resume_at:
            ctx.mark_sleep_completed(sleep_id)
            logger.debug(
                f"Sleep {sleep_id} duration elapsed during resume",
                run_id=ctx.run_id,
                sleep_id=sleep_id,
            )
            return

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
    try:
        from pyworkflow.celery.tasks import schedule_workflow_resumption

        schedule_workflow_resumption(ctx.run_id, resume_at)
        logger.info(
            f"Scheduled automatic workflow resumption",
            run_id=ctx.run_id,
            resume_at=resume_at.isoformat(),
        )
    except (ImportError, Exception) as e:
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
    """Generate unique sleep ID."""
    if name:
        content = f"{run_id}:{name}"
        hash_hex = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"sleep_{name}_{hash_hex}"
    else:
        return f"sleep_{uuid.uuid4().hex[:16]}"


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
