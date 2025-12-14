"""
Sleep primitive for workflow delays.

Allows workflows to pause execution for a specified duration without
holding resources. The workflow will suspend and can be resumed after
the delay period.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Optional, Union

from loguru import logger

from pyworkflow.core.context import get_current_context, has_current_context
from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.engine.events import (
    EventType,
    create_sleep_completed_event,
    create_sleep_started_event,
)
from pyworkflow.utils.duration import parse_duration


async def sleep(
    duration: Union[str, int, timedelta, datetime],
    name: Optional[str] = None,
) -> None:
    """
    Suspend workflow execution for a specified duration.

    This is a durable sleep that persists across process restarts. The workflow
    will suspend and can be resumed after the delay period.

    Args:
        duration: How long to sleep:
            - str: Duration string ("5s", "2m", "1h", "3d", "1w")
            - int: Seconds
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

        # Sleep until specific time
        await sleep(datetime(2025, 1, 15, 10, 30))

        # Named sleep for debugging
        await sleep("5m", name="wait_for_rate_limit")

    Raises:
        SuspensionSignal: To pause workflow execution
    """
    import asyncio

    # If not in workflow context, use regular asyncio.sleep
    if not has_current_context():
        logger.debug(
            f"Sleep called outside workflow, using asyncio.sleep for {duration}"
        )
        delay_seconds = _calculate_delay_seconds(duration)
        await asyncio.sleep(delay_seconds)
        return

    ctx = get_current_context()

    # Transient mode: use regular asyncio.sleep
    if not ctx.is_durable():
        logger.debug(
            f"Sleep in transient mode, using asyncio.sleep for {duration}",
            run_id=ctx.run_id,
        )
        delay_seconds = _calculate_delay_seconds(duration)
        await asyncio.sleep(delay_seconds)
        return

    # Durable mode: use durable sleep with event sourcing

    # Generate sleep ID (deterministic based on name or sequence)
    sleep_id = _generate_sleep_id(name, ctx.run_id)

    # Calculate when sleep should complete
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
        # During replay, we should skip past sleeps that have completed
        now = datetime.now(UTC)
        if now >= resume_at:
            # Sleep duration has elapsed, mark as completed
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
        # Celery not available or Redis not running (e.g., in tests)
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
    Generate unique sleep ID.

    If name is provided, use it to create a deterministic ID.
    Otherwise, generate a unique ID.

    Args:
        name: Optional sleep name
        run_id: Workflow run ID

    Returns:
        Unique sleep ID
    """
    if name:
        # Deterministic ID based on name and run_id
        content = f"{run_id}:{name}"
        hash_hex = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"sleep_{name}_{hash_hex}"
    else:
        # Unique ID
        return f"sleep_{uuid.uuid4().hex[:16]}"


def _calculate_resume_time(duration: Union[str, int, timedelta, datetime]) -> datetime:
    """
    Calculate when the sleep should resume.

    Args:
        duration: Sleep duration

    Returns:
        UTC datetime when sleep should complete
    """
    if isinstance(duration, datetime):
        # Sleep until specific time
        return duration

    # Calculate delay seconds
    delay_seconds = _calculate_delay_seconds(duration)

    # Return current time + delay
    return datetime.now(UTC) + timedelta(seconds=delay_seconds)


def _calculate_delay_seconds(duration: Union[str, int, timedelta, datetime]) -> int:
    """
    Calculate delay in seconds.

    Args:
        duration: Sleep duration

    Returns:
        Delay in seconds
    """
    if isinstance(duration, datetime):
        # Calculate seconds until that time
        now = datetime.now(UTC)
        if duration <= now:
            raise ValueError(
                f"Cannot sleep until past time: {duration} (now: {now})"
            )
        delta = duration - now
        return int(delta.total_seconds())

    # Use the unified parse_duration function for all other types
    return parse_duration(duration)
