"""
Schedule primitives for workflow scheduling.

Provides functions to create, manage, and query schedules.

Examples:
    # Create a cron-based schedule
    schedule = await create_schedule(
        "daily_report",
        ScheduleSpec(cron="0 9 * * *"),
    )

    # Create an interval-based schedule
    schedule = await create_schedule(
        "health_check",
        ScheduleSpec(interval="5m"),
    )

    # Pause a schedule
    await pause_schedule(schedule.schedule_id)

    # Resume a schedule
    await resume_schedule(schedule.schedule_id)
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from pyworkflow.core.registry import get_workflow
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import (
    OverlapPolicy,
    Schedule,
    ScheduleSpec,
    ScheduleStatus,
)
from pyworkflow.utils.schedule import calculate_next_run_time


async def create_schedule(
    workflow_name: str,
    spec: ScheduleSpec,
    *args: Any,
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP,
    schedule_id: str | None = None,
    storage: StorageBackend | None = None,
    **kwargs: Any,
) -> Schedule:
    """
    Create a new schedule for a workflow.

    Args:
        workflow_name: Name of the workflow to schedule
        spec: Schedule specification (cron, interval, or calendar)
        *args: Positional arguments for the workflow
        overlap_policy: How to handle overlapping runs
        schedule_id: Optional custom schedule ID
        storage: Storage backend (uses global config if not provided)
        **kwargs: Keyword arguments for the workflow

    Returns:
        Created Schedule

    Raises:
        ValueError: If workflow not found or invalid spec

    Examples:
        # Every day at 9 AM
        schedule = await create_schedule(
            "daily_report",
            ScheduleSpec(cron="0 9 * * *"),
        )

        # Every 5 minutes with skip overlap
        schedule = await create_schedule(
            "health_check",
            ScheduleSpec(interval="5m"),
            overlap_policy=OverlapPolicy.SKIP,
        )

        # Calendar-based: 1st of every month at midnight
        from pyworkflow.storage.schemas import CalendarSpec
        schedule = await create_schedule(
            "monthly_billing",
            ScheduleSpec(calendar=[CalendarSpec(day_of_month=1, hour=0, minute=0)]),
        )
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required for schedules")

    # Validate workflow exists
    workflow_meta = get_workflow(workflow_name)
    if not workflow_meta:
        raise ValueError(f"Workflow '{workflow_name}' not found in registry")

    # Validate spec
    if not spec.cron and not spec.interval and not spec.calendar:
        raise ValueError("Schedule spec must have cron, interval, or calendar")

    # Validate cron expression if provided
    if spec.cron:
        from pyworkflow.utils.schedule import validate_cron_expression

        if not validate_cron_expression(spec.cron):
            raise ValueError(f"Invalid cron expression: {spec.cron}")

    # Generate schedule_id
    if schedule_id is None:
        schedule_id = f"sched_{uuid.uuid4().hex[:12]}"

    # Calculate first run time
    next_run_time = calculate_next_run_time(spec)

    schedule = Schedule(
        schedule_id=schedule_id,
        workflow_name=workflow_name,
        spec=spec,
        status=ScheduleStatus.ACTIVE,
        args=serialize_args(*args),
        kwargs=serialize_kwargs(**kwargs),
        overlap_policy=overlap_policy,
        created_at=datetime.now(UTC),
        next_run_time=next_run_time,
    )

    await storage.create_schedule(schedule)

    logger.info(
        f"Created schedule: {schedule_id}",
        workflow_name=workflow_name,
        next_run_time=next_run_time.isoformat() if next_run_time else None,
    )

    return schedule


async def get_schedule(
    schedule_id: str,
    storage: StorageBackend | None = None,
) -> Schedule | None:
    """
    Get a schedule by ID.

    Args:
        schedule_id: Schedule identifier
        storage: Storage backend

    Returns:
        Schedule if found, None otherwise
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required")

    return await storage.get_schedule(schedule_id)


async def list_schedules(
    workflow_name: str | None = None,
    status: ScheduleStatus | None = None,
    limit: int = 100,
    offset: int = 0,
    storage: StorageBackend | None = None,
) -> list[Schedule]:
    """
    List schedules with optional filtering.

    Args:
        workflow_name: Filter by workflow name
        status: Filter by status
        limit: Maximum number of results
        offset: Number of results to skip
        storage: Storage backend

    Returns:
        List of Schedule instances
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required")

    return await storage.list_schedules(
        workflow_name=workflow_name,
        status=status,
        limit=limit,
        offset=offset,
    )


async def update_schedule(
    schedule_id: str,
    spec: ScheduleSpec | None = None,
    overlap_policy: OverlapPolicy | None = None,
    storage: StorageBackend | None = None,
) -> Schedule:
    """
    Update an existing schedule.

    Args:
        schedule_id: Schedule identifier
        spec: New schedule specification (optional)
        overlap_policy: New overlap policy (optional)
        storage: Storage backend

    Returns:
        Updated Schedule

    Raises:
        ValueError: If schedule not found
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required")

    schedule = await storage.get_schedule(schedule_id)
    if not schedule:
        raise ValueError(f"Schedule not found: {schedule_id}")

    if spec is not None:
        schedule.spec = spec
        # Recalculate next run time
        schedule.next_run_time = calculate_next_run_time(spec)

    if overlap_policy is not None:
        schedule.overlap_policy = overlap_policy

    schedule.updated_at = datetime.now(UTC)
    await storage.update_schedule(schedule)

    logger.info(f"Updated schedule: {schedule_id}")
    return schedule


async def pause_schedule(
    schedule_id: str,
    storage: StorageBackend | None = None,
) -> Schedule:
    """
    Pause a schedule.

    A paused schedule will not trigger any new workflow runs until resumed.

    Args:
        schedule_id: Schedule identifier
        storage: Storage backend

    Returns:
        Updated Schedule

    Raises:
        ValueError: If schedule not found
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required")

    schedule = await storage.get_schedule(schedule_id)
    if not schedule:
        raise ValueError(f"Schedule not found: {schedule_id}")

    schedule.status = ScheduleStatus.PAUSED
    schedule.updated_at = datetime.now(UTC)
    await storage.update_schedule(schedule)

    logger.info(f"Paused schedule: {schedule_id}")
    return schedule


async def resume_schedule(
    schedule_id: str,
    storage: StorageBackend | None = None,
) -> Schedule:
    """
    Resume a paused schedule.

    Recalculates the next run time from now.

    Args:
        schedule_id: Schedule identifier
        storage: Storage backend

    Returns:
        Updated Schedule with new next_run_time

    Raises:
        ValueError: If schedule not found
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required")

    schedule = await storage.get_schedule(schedule_id)
    if not schedule:
        raise ValueError(f"Schedule not found: {schedule_id}")

    schedule.status = ScheduleStatus.ACTIVE
    schedule.updated_at = datetime.now(UTC)
    schedule.next_run_time = calculate_next_run_time(schedule.spec)
    await storage.update_schedule(schedule)

    logger.info(
        f"Resumed schedule: {schedule_id}",
        next_run_time=schedule.next_run_time.isoformat() if schedule.next_run_time else None,
    )
    return schedule


async def delete_schedule(
    schedule_id: str,
    storage: StorageBackend | None = None,
) -> None:
    """
    Delete a schedule (soft delete).

    The schedule record is preserved for audit purposes but marked as deleted.

    Args:
        schedule_id: Schedule identifier
        storage: Storage backend

    Raises:
        ValueError: If schedule not found
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required")

    await storage.delete_schedule(schedule_id)
    logger.info(f"Deleted schedule: {schedule_id}")


async def trigger_schedule(
    schedule_id: str,
    storage: StorageBackend | None = None,
) -> str:
    """
    Manually trigger a schedule immediately.

    This bypasses the normal scheduling and executes the workflow immediately.
    Does not affect the regular schedule timing.

    Uses the configured runtime (local or celery) to execute the workflow.

    Args:
        schedule_id: Schedule identifier
        storage: Storage backend

    Returns:
        The workflow run ID

    Raises:
        ValueError: If schedule not found
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required")

    schedule = await storage.get_schedule(schedule_id)
    if not schedule:
        raise ValueError(f"Schedule not found: {schedule_id}")

    # Get workflow function
    workflow_meta = get_workflow(schedule.workflow_name)
    if not workflow_meta:
        raise ValueError(f"Workflow '{schedule.workflow_name}' not found in registry")

    # Deserialize args and kwargs
    from pyworkflow.serialization.decoder import deserialize_args, deserialize_kwargs

    args = deserialize_args(schedule.args)
    kwargs = deserialize_kwargs(schedule.kwargs)

    # Use runtime-agnostic start() which delegates to configured runtime
    from pyworkflow.engine.executor import start

    run_id = await start(
        workflow_meta.func,
        *args,
        storage=storage,
        durable=True,
        **kwargs,
    )

    # Update schedule stats
    now = datetime.now(UTC)
    schedule.last_run_at = now
    schedule.total_runs += 1
    schedule.next_run_time = calculate_next_run_time(schedule.spec, last_run=now, now=now)
    await storage.update_schedule(schedule)

    logger.info(f"Manually triggered schedule: {schedule_id}", run_id=run_id)
    return run_id


async def backfill_schedule(
    schedule_id: str,
    start_time: datetime,
    end_time: datetime,
    storage: StorageBackend | None = None,
) -> list[str]:
    """
    Backfill missed runs for a schedule.

    Creates workflow runs for all scheduled times between start_time and end_time.
    Useful for catching up after scheduler downtime.

    Uses the configured runtime (local or celery) to execute the workflows.

    Args:
        schedule_id: Schedule to backfill
        start_time: Start of backfill period
        end_time: End of backfill period
        storage: Storage backend

    Returns:
        List of created run IDs

    Raises:
        ValueError: If schedule not found
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required")

    schedule = await storage.get_schedule(schedule_id)
    if not schedule:
        raise ValueError(f"Schedule not found: {schedule_id}")

    from pyworkflow.engine.events import (
        create_schedule_backfill_completed_event,
        create_schedule_backfill_started_event,
    )
    from pyworkflow.serialization.decoder import deserialize_args, deserialize_kwargs
    from pyworkflow.utils.schedule import calculate_backfill_times

    backfill_times = calculate_backfill_times(schedule.spec, start_time, end_time)

    if not backfill_times:
        logger.info(f"No backfill times found for schedule: {schedule_id}")
        return []

    # Record backfill started event
    started_event = create_schedule_backfill_started_event(
        run_id=schedule_id,
        schedule_id=schedule_id,
        start_time=start_time,
        end_time=end_time,
        expected_runs=len(backfill_times),
    )
    await storage.record_event(started_event)

    # Get workflow function
    workflow_meta = get_workflow(schedule.workflow_name)
    if not workflow_meta:
        raise ValueError(f"Workflow '{schedule.workflow_name}' not found in registry")

    # Deserialize args and kwargs
    args = deserialize_args(schedule.args)
    kwargs = deserialize_kwargs(schedule.kwargs)

    # Use runtime-agnostic start() which delegates to configured runtime
    from pyworkflow.engine.executor import start

    run_ids: list[str] = []

    for scheduled_time in backfill_times:
        try:
            run_id = await start(
                workflow_meta.func,
                *args,
                storage=storage,
                durable=True,
                **kwargs,
            )
            run_ids.append(run_id)
            logger.debug(
                f"Backfill run started for {schedule_id}",
                run_id=run_id,
                scheduled_time=scheduled_time.isoformat(),
            )
        except Exception as e:
            logger.error(
                f"Failed to start backfill run for {schedule_id}",
                scheduled_time=scheduled_time.isoformat(),
                error=str(e),
            )

    # Record backfill completed event
    completed_event = create_schedule_backfill_completed_event(
        run_id=schedule_id,
        schedule_id=schedule_id,
        runs_created=len(run_ids),
        run_ids=run_ids,
    )
    await storage.record_event(completed_event)

    logger.info(
        f"Completed backfill for schedule: {schedule_id}",
        count=len(run_ids),
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
    )

    return run_ids
