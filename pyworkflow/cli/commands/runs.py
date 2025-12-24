"""Workflow run management commands."""

import json
import click
from typing import Optional
from datetime import datetime

import pyworkflow
from pyworkflow import RunStatus
from pyworkflow.cli.utils.async_helpers import async_command
from pyworkflow.cli.utils.storage import create_storage
from pyworkflow.cli.output.formatters import (
    format_table,
    format_json,
    format_plain,
    format_key_value,
    format_status,
    format_event_type,
    print_success,
    print_error,
    print_info,
)


@click.group(name="runs")
def runs() -> None:
    """Manage workflow runs (list, status, logs)."""
    pass


@runs.command(name="list")
@click.option(
    "--workflow",
    help="Filter by workflow name",
)
@click.option(
    "--status",
    type=click.Choice([s.value for s in RunStatus], case_sensitive=False),
    help="Filter by run status",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum number of runs to display (default: 20)",
)
@click.pass_context
@async_command
async def list_runs(
    ctx: click.Context,
    workflow: Optional[str],
    status: Optional[str],
    limit: int,
) -> None:
    """
    List workflow runs.

    Examples:

        # List all runs
        pyworkflow runs list

        # List runs for specific workflow
        pyworkflow runs list --workflow my_workflow

        # List failed runs
        pyworkflow runs list --status failed

        # List with limit
        pyworkflow runs list --limit 10
    """
    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Parse status filter
    status_filter = RunStatus(status) if status else None

    # List runs
    try:
        runs_list = await storage.list_runs(
            workflow_name=workflow,
            status=status_filter,
            limit=limit,
        )

        if not runs_list:
            print_info("No workflow runs found")
            return

        # Calculate durations
        for run in runs_list:
            if run.started_at and run.completed_at:
                duration = (run.completed_at - run.started_at).total_seconds()
                run.duration = f"{duration:.1f}s"
            elif run.started_at:
                duration = (datetime.now() - run.started_at.replace(tzinfo=None)).total_seconds()
                run.duration = f"{duration:.1f}s (ongoing)"
            else:
                run.duration = "-"

        # Format output
        if output == "json":
            data = [
                {
                    "run_id": run.run_id,
                    "workflow_name": run.workflow_name,
                    "status": run.status.value,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    "duration": run.duration,
                }
                for run in runs_list
            ]
            format_json(data)

        elif output == "plain":
            run_ids = [run.run_id for run in runs_list]
            format_plain(run_ids)

        else:  # table (displays as list)
            data = [
                {
                    "Run ID": run.run_id,
                    "Workflow": run.workflow_name,
                    "Status": run.status.value,
                    "Started": run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else "-",
                    "Duration": run.duration,
                }
                for run in runs_list
            ]
            format_table(
                data,
                ["Run ID", "Workflow", "Status", "Started", "Duration"],
                title="Workflow Runs",
            )

    except Exception as e:
        print_error(f"Failed to list runs: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@runs.command(name="status")
@click.argument("run_id")
@click.pass_context
@async_command
async def run_status(ctx: click.Context, run_id: str) -> None:
    """
    Show workflow run status and details.

    Args:
        RUN_ID: Workflow run identifier

    Examples:

        pyworkflow runs status run_abc123def456
    """
    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Get workflow run
    try:
        run = await pyworkflow.get_workflow_run(run_id, storage=storage)

        if not run:
            print_error(f"Workflow run '{run_id}' not found")
            raise click.Abort()

        # Calculate duration
        if run.started_at and run.completed_at:
            duration = (run.completed_at - run.started_at).total_seconds()
            duration_str = f"{duration:.1f}s"
        elif run.started_at:
            duration = (datetime.now() - run.started_at.replace(tzinfo=None)).total_seconds()
            duration_str = f"{duration:.1f}s (ongoing)"
        else:
            duration_str = "-"

        # Format output
        if output == "json":
            data = {
                "run_id": run.run_id,
                "workflow_name": run.workflow_name,
                "status": run.status.value,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "duration": duration_str,
                "input_args": json.loads(run.input_args) if run.input_args else None,
                "input_kwargs": json.loads(run.input_kwargs) if run.input_kwargs else None,
                "result": json.loads(run.result) if run.result else None,
                "error": run.error,
                "metadata": run.metadata,
            }
            format_json(data)

        else:  # table or plain (use key-value format)
            data = {
                "Run ID": run.run_id,
                "Workflow": run.workflow_name,
                "Status": run.status.value,
                "Created": run.created_at.strftime("%Y-%m-%d %H:%M:%S") if run.created_at else "-",
                "Started": run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else "-",
                "Completed": run.completed_at.strftime("%Y-%m-%d %H:%M:%S") if run.completed_at else "-",
                "Duration": duration_str,
            }

            # Add input args if present
            if run.input_kwargs:
                try:
                    kwargs = json.loads(run.input_kwargs)
                    if kwargs:
                        data["Input Arguments"] = json.dumps(kwargs, indent=2)
                except:
                    pass

            # Add result or error
            if run.result:
                try:
                    result = json.loads(run.result)
                    data["Result"] = json.dumps(result, indent=2) if not isinstance(result, str) else result
                except:
                    data["Result"] = run.result

            if run.error:
                data["Error"] = run.error

            # Add metadata if present
            if run.metadata:
                data["Metadata"] = json.dumps(run.metadata, indent=2)

            format_key_value(data, title=f"Workflow Run: {run_id}")

    except Exception as e:
        print_error(f"Failed to get run status: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@runs.command(name="logs")
@click.argument("run_id")
@click.option(
    "--filter",
    "event_filter",
    help="Filter events by type (e.g., step_completed, workflow_failed)",
)
@click.pass_context
@async_command
async def run_logs(
    ctx: click.Context,
    run_id: str,
    event_filter: Optional[str],
) -> None:
    """
    Show workflow execution event log.

    Args:
        RUN_ID: Workflow run identifier

    Examples:

        # Show all events
        pyworkflow runs logs run_abc123def456

        # Filter step completion events
        pyworkflow runs logs run_abc123def456 --filter step_completed

        # JSON output
        pyworkflow --output json runs logs run_abc123def456
    """
    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Get events
    try:
        events = await pyworkflow.get_workflow_events(run_id, storage=storage)

        if not events:
            print_info(f"No events found for run: {run_id}")
            return

        # Filter events if requested
        if event_filter:
            events = [e for e in events if event_filter.lower() in e.type.value.lower()]

            if not events:
                print_info(f"No events matching filter: {event_filter}")
                return

        # Format output
        if output == "json":
            data = [
                {
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                    "type": event.type.value,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                    "data": event.data,
                }
                for event in events
            ]
            format_json(data)

        elif output == "plain":
            lines = [f"{event.sequence}: {event.type.value}" for event in events]
            format_plain(lines)

        else:  # table (displays as list with full data)
            from pyworkflow.cli.output.styles import Colors, RESET, DIM

            print(f"\n{Colors.PRIMARY}{Colors.bold(f'Event Log: {run_id}')}{RESET}")
            print(f"{DIM}{'─' * 60}{RESET}")
            print(f"Total events: {len(events)}\n")

            for event in events:
                seq = event.sequence or "-"
                event_type = event.type.value
                timestamp = event.timestamp.strftime("%H:%M:%S.%f")[:-3] if event.timestamp else "-"

                # Color code event types
                type_color = {
                    "workflow.started": Colors.BLUE,
                    "workflow.completed": Colors.GREEN,
                    "workflow.failed": Colors.RED,
                    "workflow.interrupted": Colors.YELLOW,
                    "step.started": Colors.CYAN,
                    "step.completed": Colors.GREEN,
                    "step.failed": Colors.RED,
                    "step.retrying": Colors.YELLOW,
                    "sleep.started": Colors.MAGENTA,
                    "sleep.completed": Colors.MAGENTA,
                    "hook.created": Colors.YELLOW,
                    "hook.received": Colors.GREEN,
                }.get(event_type, "")

                print(f"{Colors.bold(str(seq))}")
                print(f"   Type: {type_color}{event_type}{RESET}")
                print(f"   Timestamp: {timestamp}")

                # Pretty print data if not empty
                if event.data:
                    data_str = json.dumps(event.data, indent=6)
                    # Indent each line of the JSON
                    data_lines = data_str.split('\n')
                    print(f"   Data: {data_lines[0]}")
                    for line in data_lines[1:]:
                        print(f"   {line}")
                else:
                    print(f"   Data: {DIM}{{}}{RESET}")

                print()  # Blank line between events

    except Exception as e:
        print_error(f"Failed to get event log: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()
