"""
@scheduled_workflow decorator for defining workflows with built-in scheduling.

This decorator combines the @workflow decorator with schedule configuration,
enabling workflows to be automatically scheduled based on cron expressions,
intervals, or calendar specifications.

Examples:
    # Cron-based schedule (every day at 9 AM)
    @scheduled_workflow(cron="0 9 * * *")
    async def daily_report():
        return await generate_report()

    # Interval-based schedule (every 5 minutes)
    @scheduled_workflow(interval="5m")
    async def health_check():
        return await check_system_health()

    # Combined with workflow options
    @scheduled_workflow(
        cron="0 0 * * 0",
        name="weekly_cleanup",
        overlap_policy=OverlapPolicy.SKIP,
        timezone="America/New_York",
    )
    async def weekly_cleanup():
        return await cleanup_old_data()
"""

import functools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pyworkflow.core.registry import register_workflow
from pyworkflow.storage.schemas import CalendarSpec, OverlapPolicy, ScheduleSpec


@dataclass
class ScheduledWorkflowMetadata:
    """Metadata for a scheduled workflow."""

    workflow_name: str
    spec: ScheduleSpec
    overlap_policy: OverlapPolicy
    func: Callable[..., Any]


# Registry for scheduled workflows (separate from main workflow registry)
_scheduled_workflows: dict[str, ScheduledWorkflowMetadata] = {}


def scheduled_workflow(
    cron: str | None = None,
    interval: str | None = None,
    calendar: list[CalendarSpec] | None = None,
    timezone: str = "UTC",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    jitter: str | None = None,
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP,
    name: str | None = None,
    durable: bool | None = None,
    max_duration: str | None = None,
    recover_on_worker_loss: bool | None = None,
    max_recovery_attempts: int | None = None,
) -> Callable:
    """
    Decorator to define a workflow with built-in scheduling configuration.

    This decorator combines @workflow functionality with schedule specification,
    allowing the workflow to be automatically scheduled when registered with
    a scheduler.

    Args:
        cron: Cron expression for scheduling (e.g., "0 9 * * *" for daily at 9 AM)
        interval: Interval duration (e.g., "5m", "1h", "30s")
        calendar: List of CalendarSpec for calendar-based scheduling
        timezone: Timezone for schedule (default: "UTC")
        start_at: Optional start time for the schedule
        end_at: Optional end time for the schedule
        jitter: Random delay to prevent thundering herd (e.g., "30s")
        overlap_policy: How to handle overlapping runs (default: SKIP)
        name: Optional workflow name (defaults to function name)
        durable: Whether workflow is durable (None = use configured default)
        max_duration: Optional max duration (e.g., "1h", "30m")
        recover_on_worker_loss: Whether to auto-recover on worker failure
        max_recovery_attempts: Max recovery attempts on worker failure

    Returns:
        Decorated workflow function with schedule metadata

    Raises:
        ValueError: If no schedule specification provided

    Examples:
        # Every day at 9 AM
        @scheduled_workflow(cron="0 9 * * *")
        async def daily_report():
            return await generate_report()

        # Every 5 minutes with skip policy
        @scheduled_workflow(
            interval="5m",
            overlap_policy=OverlapPolicy.SKIP,
        )
        async def health_check():
            return await check_system_health()

        # First of every month at midnight UTC
        @scheduled_workflow(
            calendar=[CalendarSpec(day_of_month=1, hour=0, minute=0)],
            timezone="UTC",
        )
        async def monthly_billing():
            return await process_billing()

        # Complex schedule with workflow options
        @scheduled_workflow(
            cron="0 */4 * * *",  # Every 4 hours
            name="sync_data",
            overlap_policy=OverlapPolicy.BUFFER_ONE,
            recover_on_worker_loss=True,
            max_recovery_attempts=5,
        )
        async def sync_external_data():
            return await sync_data()
    """
    # Validate at least one schedule type is provided
    if not cron and not interval and not calendar:
        raise ValueError("scheduled_workflow requires at least one of: cron, interval, or calendar")

    def decorator(func: Callable) -> Callable:
        workflow_name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        # Register as a regular workflow first
        register_workflow(
            name=workflow_name,
            func=wrapper,
            original_func=func,
            max_duration=max_duration,
        )

        # Store standard workflow metadata on wrapper
        wrapper.__workflow__ = True  # type: ignore[attr-defined]
        wrapper.__workflow_name__ = workflow_name  # type: ignore[attr-defined]
        wrapper.__workflow_durable__ = durable  # type: ignore[attr-defined]
        wrapper.__workflow_max_duration__ = max_duration  # type: ignore[attr-defined]
        wrapper.__workflow_recover_on_worker_loss__ = recover_on_worker_loss  # type: ignore[attr-defined]
        wrapper.__workflow_max_recovery_attempts__ = max_recovery_attempts  # type: ignore[attr-defined]

        # Create schedule spec
        spec = ScheduleSpec(
            cron=cron,
            interval=interval,
            calendar=calendar,
            timezone=timezone,
            start_at=start_at,
            end_at=end_at,
            jitter=jitter,
        )

        # Store schedule metadata on wrapper
        wrapper.__scheduled__ = True  # type: ignore[attr-defined]
        wrapper.__schedule_spec__ = spec  # type: ignore[attr-defined]
        wrapper.__overlap_policy__ = overlap_policy  # type: ignore[attr-defined]

        # Register in scheduled workflows registry
        scheduled_meta = ScheduledWorkflowMetadata(
            workflow_name=workflow_name,
            spec=spec,
            overlap_policy=overlap_policy,
            func=wrapper,
        )
        _scheduled_workflows[workflow_name] = scheduled_meta

        return wrapper

    return decorator


def get_scheduled_workflow(name: str) -> ScheduledWorkflowMetadata | None:
    """
    Get scheduled workflow metadata by name.

    Args:
        name: Workflow name

    Returns:
        ScheduledWorkflowMetadata if found, None otherwise
    """
    return _scheduled_workflows.get(name)


def list_scheduled_workflows() -> dict[str, ScheduledWorkflowMetadata]:
    """
    List all registered scheduled workflows.

    Returns:
        Dictionary mapping workflow names to their schedule metadata
    """
    return _scheduled_workflows.copy()


def register_scheduled_workflow(
    workflow_name: str,
    spec: ScheduleSpec,
    overlap_policy: OverlapPolicy,
    func: Callable[..., Any],
) -> None:
    """
    Manually register a scheduled workflow.

    This is useful when you want to add scheduling to an existing workflow
    without using the @scheduled_workflow decorator.

    Args:
        workflow_name: Name of the workflow to schedule
        spec: Schedule specification
        overlap_policy: How to handle overlapping runs
        func: The workflow function

    Examples:
        from pyworkflow import workflow
        from pyworkflow.core.scheduled import register_scheduled_workflow

        @workflow
        async def my_workflow():
            pass

        # Add scheduling later
        register_scheduled_workflow(
            "my_workflow",
            ScheduleSpec(cron="0 9 * * *"),
            OverlapPolicy.SKIP,
            my_workflow,
        )
    """
    scheduled_meta = ScheduledWorkflowMetadata(
        workflow_name=workflow_name,
        spec=spec,
        overlap_policy=overlap_policy,
        func=func,
    )
    _scheduled_workflows[workflow_name] = scheduled_meta


def unregister_scheduled_workflow(workflow_name: str) -> bool:
    """
    Unregister a scheduled workflow.

    Args:
        workflow_name: Name of the workflow to unregister

    Returns:
        True if workflow was unregistered, False if not found
    """
    if workflow_name in _scheduled_workflows:
        del _scheduled_workflows[workflow_name]
        return True
    return False


def clear_scheduled_workflows() -> None:
    """Clear all scheduled workflow registrations (useful for testing)."""
    _scheduled_workflows.clear()


async def activate_scheduled_workflows(
    storage: Any = None,
    schedule_id_prefix: str = "auto_",
) -> list[str]:
    """
    Activate all registered scheduled workflows by creating schedules in storage.

    This function takes all workflows decorated with @scheduled_workflow and
    creates corresponding schedules in the storage backend.

    Args:
        storage: Storage backend (uses global config if not provided)
        schedule_id_prefix: Prefix for generated schedule IDs

    Returns:
        List of created schedule IDs

    Examples:
        from pyworkflow.core.scheduled import activate_scheduled_workflows

        # Activate all @scheduled_workflow decorated functions
        schedule_ids = await activate_scheduled_workflows()
        print(f"Created {len(schedule_ids)} schedules")
    """
    if storage is None:
        from pyworkflow.config import get_config

        storage = get_config().storage

    if storage is None:
        raise ValueError("Storage backend required to activate scheduled workflows")

    from pyworkflow.primitives.schedule import create_schedule

    created_ids: list[str] = []

    for workflow_name, meta in _scheduled_workflows.items():
        schedule_id = f"{schedule_id_prefix}{workflow_name}"

        # Check if schedule already exists
        existing = await storage.get_schedule(schedule_id)
        if existing:
            # Skip if already exists
            continue

        schedule = await create_schedule(
            workflow_name=workflow_name,
            spec=meta.spec,
            overlap_policy=meta.overlap_policy,
            schedule_id=schedule_id,
            storage=storage,
        )
        created_ids.append(schedule.schedule_id)

    return created_ids
