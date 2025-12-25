"""Schedule management CLI commands."""

from datetime import datetime

import click

from pyworkflow import OverlapPolicy, ScheduleSpec, ScheduleStatus
from pyworkflow.cli.output.formatters import (
    format_json,
    format_key_value,
    format_plain,
    format_table,
    print_error,
    print_info,
    print_success,
    print_warning,
)
from pyworkflow.cli.utils.async_helpers import async_command
from pyworkflow.cli.utils.storage import create_storage
from pyworkflow.utils.schedule import describe_schedule


@click.group(name="schedules")
def schedules() -> None:
    """Manage workflow schedules (cron, interval, calendar-based)."""
    pass


@schedules.command(name="list")
@click.option(
    "--workflow",
    help="Filter by workflow name",
)
@click.option(
    "--status",
    type=click.Choice([s.value for s in ScheduleStatus], case_sensitive=False),
    help="Filter by schedule status",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum number of schedules to display (default: 20)",
)
@click.pass_context
@async_command
async def list_schedules_cmd(
    ctx: click.Context,
    workflow: str | None,
    status: str | None,
    limit: int,
) -> None:
    """
    List workflow schedules.

    Examples:

        # List all schedules
        pyworkflow schedules list

        # List schedules for specific workflow
        pyworkflow schedules list --workflow my_workflow

        # List only active schedules
        pyworkflow schedules list --status active

        # JSON output
        pyworkflow --output json schedules list
    """
    from pyworkflow.primitives.schedule import list_schedules

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Parse status filter
    status_filter = ScheduleStatus(status) if status else None

    try:
        schedules_list = await list_schedules(
            workflow_name=workflow,
            status=status_filter,
            limit=limit,
            storage=storage,
        )

        if not schedules_list:
            print_info("No schedules found")
            return

        # Format output
        if output == "json":
            data = [
                {
                    "schedule_id": s.schedule_id,
                    "workflow_name": s.workflow_name,
                    "status": s.status.value,
                    "spec": describe_schedule(s.spec),
                    "overlap_policy": s.overlap_policy.value,
                    "next_run_time": s.next_run_time.isoformat() if s.next_run_time else None,
                    "total_runs": s.total_runs,
                    "successful_runs": s.successful_runs,
                    "failed_runs": s.failed_runs,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in schedules_list
            ]
            format_json(data)

        elif output == "plain":
            schedule_ids = [s.schedule_id for s in schedules_list]
            format_plain(schedule_ids)

        else:  # table
            data = [
                {
                    "Schedule ID": s.schedule_id,
                    "Workflow": s.workflow_name,
                    "Status": s.status.value,
                    "Schedule": describe_schedule(s.spec),
                    "Next Run": s.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
                    if s.next_run_time
                    else "-",
                    "Runs": f"{s.successful_runs}/{s.total_runs}",
                }
                for s in schedules_list
            ]
            format_table(
                data,
                ["Schedule ID", "Workflow", "Status", "Schedule", "Next Run", "Runs"],
                title="Workflow Schedules",
            )

    except Exception as e:
        print_error(f"Failed to list schedules: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@schedules.command(name="create")
@click.argument("workflow_name")
@click.option(
    "--cron",
    help="Cron expression (e.g., '0 9 * * *' for daily at 9 AM)",
)
@click.option(
    "--interval",
    help="Interval duration (e.g., '5m', '1h', '30s')",
)
@click.option(
    "--timezone",
    default="UTC",
    help="Timezone for schedule (default: UTC)",
)
@click.option(
    "--overlap",
    type=click.Choice([p.value for p in OverlapPolicy], case_sensitive=False),
    default="skip",
    help="Overlap policy (default: skip)",
)
@click.option(
    "--schedule-id",
    help="Custom schedule ID (optional)",
)
@click.pass_context
@async_command
async def create_schedule_cmd(
    ctx: click.Context,
    workflow_name: str,
    cron: str | None,
    interval: str | None,
    timezone: str,
    overlap: str,
    schedule_id: str | None,
) -> None:
    """
    Create a new schedule for a workflow.

    Examples:

        # Create cron schedule (daily at 9 AM)
        pyworkflow schedules create my_workflow --cron "0 9 * * *"

        # Create interval schedule (every 5 minutes)
        pyworkflow schedules create my_workflow --interval 5m

        # Create with custom ID and overlap policy
        pyworkflow schedules create my_workflow --cron "0 0 * * 0" \\
            --schedule-id weekly_job --overlap buffer_one

        # Different timezone
        pyworkflow schedules create my_workflow --cron "0 9 * * *" \\
            --timezone America/New_York
    """
    from pyworkflow.primitives.schedule import create_schedule

    if not cron and not interval:
        print_error("Either --cron or --interval must be provided")
        raise click.Abort()

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Parse overlap policy
    overlap_policy = OverlapPolicy(overlap)

    # Create schedule spec
    spec = ScheduleSpec(
        cron=cron,
        interval=interval,
        timezone=timezone,
    )

    try:
        schedule = await create_schedule(
            workflow_name=workflow_name,
            spec=spec,
            overlap_policy=overlap_policy,
            schedule_id=schedule_id,
            storage=storage,
        )

        print_success(f"Created schedule: {schedule.schedule_id}")

        if output == "json":
            data = {
                "schedule_id": schedule.schedule_id,
                "workflow_name": schedule.workflow_name,
                "status": schedule.status.value,
                "spec": describe_schedule(schedule.spec),
                "overlap_policy": schedule.overlap_policy.value,
                "next_run_time": schedule.next_run_time.isoformat()
                if schedule.next_run_time
                else None,
            }
            format_json(data)
        else:
            print_info(f"Schedule: {describe_schedule(schedule.spec)}")
            if schedule.next_run_time:
                print_info(f"Next run: {schedule.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")

    except ValueError as e:
        print_error(str(e))
        raise click.Abort()
    except Exception as e:
        print_error(f"Failed to create schedule: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@schedules.command(name="show")
@click.argument("schedule_id")
@click.pass_context
@async_command
async def show_schedule_cmd(
    ctx: click.Context,
    schedule_id: str,
) -> None:
    """
    Show schedule details.

    Examples:

        pyworkflow schedules show sched_abc123

        # JSON output
        pyworkflow --output json schedules show sched_abc123
    """
    from pyworkflow.primitives.schedule import get_schedule

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        schedule = await get_schedule(schedule_id, storage=storage)

        if not schedule:
            print_error(f"Schedule '{schedule_id}' not found")
            raise click.Abort()

        if output == "json":
            data = {
                "schedule_id": schedule.schedule_id,
                "workflow_name": schedule.workflow_name,
                "status": schedule.status.value,
                "spec": {
                    "cron": schedule.spec.cron,
                    "interval": schedule.spec.interval,
                    "timezone": schedule.spec.timezone,
                },
                "overlap_policy": schedule.overlap_policy.value,
                "next_run_time": schedule.next_run_time.isoformat()
                if schedule.next_run_time
                else None,
                "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
                "total_runs": schedule.total_runs,
                "successful_runs": schedule.successful_runs,
                "failed_runs": schedule.failed_runs,
                "skipped_runs": schedule.skipped_runs,
                "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
                "updated_at": schedule.updated_at.isoformat() if schedule.updated_at else None,
            }
            format_json(data)
        else:
            data = {
                "Schedule ID": schedule.schedule_id,
                "Workflow": schedule.workflow_name,
                "Status": schedule.status.value,
                "Schedule": describe_schedule(schedule.spec),
                "Overlap Policy": schedule.overlap_policy.value,
                "Next Run": schedule.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
                if schedule.next_run_time
                else "-",
                "Last Run": schedule.last_run_at.strftime("%Y-%m-%d %H:%M:%S")
                if schedule.last_run_at
                else "-",
                "Total Runs": schedule.total_runs,
                "Successful": schedule.successful_runs,
                "Failed": schedule.failed_runs,
                "Skipped": schedule.skipped_runs,
                "Created": schedule.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if schedule.created_at
                else "-",
            }
            format_key_value(data, title=f"Schedule: {schedule_id}")

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Failed to get schedule: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@schedules.command(name="pause")
@click.argument("schedule_id")
@click.pass_context
@async_command
async def pause_schedule_cmd(
    ctx: click.Context,
    schedule_id: str,
) -> None:
    """
    Pause a schedule.

    A paused schedule will not trigger any new workflow runs until resumed.

    Examples:

        pyworkflow schedules pause sched_abc123
    """
    from pyworkflow.primitives.schedule import pause_schedule

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        schedule = await pause_schedule(schedule_id, storage=storage)
        print_success(f"Paused schedule: {schedule_id}")

        if output == "json":
            data = {
                "schedule_id": schedule.schedule_id,
                "status": schedule.status.value,
            }
            format_json(data)

    except ValueError as e:
        print_error(str(e))
        raise click.Abort()
    except Exception as e:
        print_error(f"Failed to pause schedule: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@schedules.command(name="resume")
@click.argument("schedule_id")
@click.pass_context
@async_command
async def resume_schedule_cmd(
    ctx: click.Context,
    schedule_id: str,
) -> None:
    """
    Resume a paused schedule.

    Recalculates the next run time from now.

    Examples:

        pyworkflow schedules resume sched_abc123
    """
    from pyworkflow.primitives.schedule import resume_schedule

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        schedule = await resume_schedule(schedule_id, storage=storage)
        print_success(f"Resumed schedule: {schedule_id}")

        if schedule.next_run_time:
            print_info(f"Next run: {schedule.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")

        if output == "json":
            data = {
                "schedule_id": schedule.schedule_id,
                "status": schedule.status.value,
                "next_run_time": schedule.next_run_time.isoformat()
                if schedule.next_run_time
                else None,
            }
            format_json(data)

    except ValueError as e:
        print_error(str(e))
        raise click.Abort()
    except Exception as e:
        print_error(f"Failed to resume schedule: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@schedules.command(name="delete")
@click.argument("schedule_id")
@click.option(
    "--force",
    is_flag=True,
    help="Delete without confirmation",
)
@click.pass_context
@async_command
async def delete_schedule_cmd(
    ctx: click.Context,
    schedule_id: str,
    force: bool,
) -> None:
    """
    Delete a schedule (soft delete).

    The schedule record is preserved for audit purposes but marked as deleted.

    Examples:

        # Delete with confirmation
        pyworkflow schedules delete sched_abc123

        # Force delete
        pyworkflow schedules delete sched_abc123 --force
    """
    from pyworkflow.primitives.schedule import delete_schedule, get_schedule

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        # Check if schedule exists
        schedule = await get_schedule(schedule_id, storage=storage)
        if not schedule:
            print_error(f"Schedule '{schedule_id}' not found")
            raise click.Abort()

        # Confirm deletion
        if not force:
            click.confirm(
                f"Delete schedule '{schedule_id}' for workflow '{schedule.workflow_name}'?",
                abort=True,
            )

        await delete_schedule(schedule_id, storage=storage)
        print_success(f"Deleted schedule: {schedule_id}")

        if output == "json":
            data = {
                "schedule_id": schedule_id,
                "deleted": True,
            }
            format_json(data)

    except click.Abort:
        raise
    except ValueError as e:
        print_error(str(e))
        raise click.Abort()
    except Exception as e:
        print_error(f"Failed to delete schedule: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@schedules.command(name="trigger")
@click.argument("schedule_id")
@click.pass_context
@async_command
async def trigger_schedule_cmd(
    ctx: click.Context,
    schedule_id: str,
) -> None:
    """
    Manually trigger a schedule immediately.

    This bypasses the normal scheduling and executes the workflow immediately.
    Does not affect the regular schedule timing.

    Examples:

        pyworkflow schedules trigger sched_abc123
    """
    from pyworkflow.primitives.schedule import get_schedule, trigger_schedule

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        # Check if schedule exists
        schedule = await get_schedule(schedule_id, storage=storage)
        if not schedule:
            print_error(f"Schedule '{schedule_id}' not found")
            raise click.Abort()

        await trigger_schedule(schedule_id, storage=storage)
        print_success(f"Triggered schedule: {schedule_id}")
        print_info(f"Workflow '{schedule.workflow_name}' execution queued")

        if output == "json":
            data = {
                "schedule_id": schedule_id,
                "triggered": True,
                "workflow_name": schedule.workflow_name,
            }
            format_json(data)

    except ValueError as e:
        print_error(str(e))
        raise click.Abort()
    except Exception as e:
        print_error(f"Failed to trigger schedule: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@schedules.command(name="backfill")
@click.argument("schedule_id")
@click.option(
    "--start",
    required=True,
    help="Start time for backfill (ISO format, e.g., 2024-01-01T00:00:00)",
)
@click.option(
    "--end",
    required=True,
    help="End time for backfill (ISO format, e.g., 2024-01-31T23:59:59)",
)
@click.pass_context
@async_command
async def backfill_schedule_cmd(
    ctx: click.Context,
    schedule_id: str,
    start: str,
    end: str,
) -> None:
    """
    Backfill missed runs for a schedule.

    Creates workflow runs for all scheduled times between start and end times.
    Useful for catching up after scheduler downtime.

    Examples:

        # Backfill a specific time range
        pyworkflow schedules backfill sched_abc123 \\
            --start 2024-01-01T00:00:00 \\
            --end 2024-01-31T23:59:59
    """
    from pyworkflow.primitives.schedule import backfill_schedule, get_schedule

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        # Check if schedule exists
        schedule = await get_schedule(schedule_id, storage=storage)
        if not schedule:
            print_error(f"Schedule '{schedule_id}' not found")
            raise click.Abort()

        # Parse timestamps
        try:
            start_time = datetime.fromisoformat(start)
        except ValueError:
            print_error(f"Invalid start time format: {start}")
            print_info("Expected ISO format (e.g., 2024-01-01T00:00:00)")
            raise click.Abort()

        try:
            end_time = datetime.fromisoformat(end)
        except ValueError:
            print_error(f"Invalid end time format: {end}")
            print_info("Expected ISO format (e.g., 2024-01-31T23:59:59)")
            raise click.Abort()

        if start_time >= end_time:
            print_error("Start time must be before end time")
            raise click.Abort()

        # Perform backfill
        run_ids = await backfill_schedule(
            schedule_id=schedule_id,
            start_time=start_time,
            end_time=end_time,
            storage=storage,
        )

        if run_ids:
            print_success(f"Started backfill for schedule: {schedule_id}")
            print_info(f"Created {len(run_ids)} workflow run(s)")
        else:
            print_warning("No runs to backfill in the specified time range")

        if output == "json":
            data = {
                "schedule_id": schedule_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "runs_created": len(run_ids),
                "run_ids": run_ids,
            }
            format_json(data)

    except click.Abort:
        raise
    except ValueError as e:
        print_error(str(e))
        raise click.Abort()
    except Exception as e:
        print_error(f"Failed to backfill schedule: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@schedules.command(name="update")
@click.argument("schedule_id")
@click.option(
    "--cron",
    help="New cron expression",
)
@click.option(
    "--interval",
    help="New interval duration",
)
@click.option(
    "--overlap",
    type=click.Choice([p.value for p in OverlapPolicy], case_sensitive=False),
    help="New overlap policy",
)
@click.pass_context
@async_command
async def update_schedule_cmd(
    ctx: click.Context,
    schedule_id: str,
    cron: str | None,
    interval: str | None,
    overlap: str | None,
) -> None:
    """
    Update an existing schedule.

    Examples:

        # Update cron expression
        pyworkflow schedules update sched_abc123 --cron "0 10 * * *"

        # Update overlap policy
        pyworkflow schedules update sched_abc123 --overlap buffer_one

        # Update both
        pyworkflow schedules update sched_abc123 --interval 10m --overlap allow_all
    """
    from pyworkflow.primitives.schedule import update_schedule

    if not cron and not interval and not overlap:
        print_error("At least one of --cron, --interval, or --overlap must be provided")
        raise click.Abort()

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        # Build new spec if schedule timing is being updated
        new_spec = None
        if cron or interval:
            new_spec = ScheduleSpec(
                cron=cron,
                interval=interval,
            )

        # Parse overlap policy
        overlap_policy = OverlapPolicy(overlap) if overlap else None

        schedule = await update_schedule(
            schedule_id=schedule_id,
            spec=new_spec,
            overlap_policy=overlap_policy,
            storage=storage,
        )

        print_success(f"Updated schedule: {schedule_id}")

        if output == "json":
            data = {
                "schedule_id": schedule.schedule_id,
                "workflow_name": schedule.workflow_name,
                "spec": describe_schedule(schedule.spec),
                "overlap_policy": schedule.overlap_policy.value,
                "next_run_time": schedule.next_run_time.isoformat()
                if schedule.next_run_time
                else None,
            }
            format_json(data)
        else:
            print_info(f"Schedule: {describe_schedule(schedule.spec)}")
            if schedule.next_run_time:
                print_info(f"Next run: {schedule.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")

    except ValueError as e:
        print_error(str(e))
        raise click.Abort()
    except Exception as e:
        print_error(f"Failed to update schedule: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()
