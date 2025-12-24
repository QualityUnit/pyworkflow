"""
Sleep primitive for workflow delays.

Allows workflows to pause execution for a specified duration without
holding resources. The workflow will suspend and can be resumed after
the delay period.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from loguru import logger

from pyworkflow.context import get_context, has_context
from pyworkflow.utils.duration import parse_duration


async def sleep(
    duration: str | int | float | timedelta | datetime,
    name: str | None = None,
) -> None:
    """
    Suspend workflow execution for a specified duration.

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
    # Check for workflow context
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

    # No context available - use regular asyncio.sleep
    duration_seconds = _calculate_delay_seconds(duration)
    logger.debug(
        f"Sleep called outside workflow context, using asyncio.sleep for {duration_seconds}s"
    )
    await asyncio.sleep(duration_seconds)


def _calculate_resume_time(duration: str | int | float | timedelta | datetime) -> datetime:
    """Calculate when the sleep should resume."""
    if isinstance(duration, datetime):
        return duration

    delay_seconds = _calculate_delay_seconds(duration)
    return datetime.now(UTC) + timedelta(seconds=delay_seconds)


def _calculate_delay_seconds(duration: str | int | float | timedelta | datetime) -> int:
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
