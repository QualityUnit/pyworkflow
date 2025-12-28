"""Workflow run management commands."""

import json
from datetime import datetime

import click

import pyworkflow
from pyworkflow import RunStatus, WorkflowRun
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


@click.group(name="runs")
def runs() -> None:
    """Manage workflow runs (list, status, logs)."""
    pass


@runs.command(name="list")
@click.option(
    "-q",
    "--query",
    help="Search in workflow name and input kwargs (case-insensitive)",
)
@click.option(
    "--status",
    type=click.Choice([s.value for s in RunStatus], case_sensitive=False),
    help="Filter by run status",
)
@click.option(
    "--start-time",
    type=click.DateTime(),
    help="Filter runs started at or after this time (ISO 8601 format)",
)
@click.option(
    "--end-time",
    type=click.DateTime(),
    help="Filter runs started before this time (ISO 8601 format)",
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
    query: str | None,
    status: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
    limit: int,
) -> None:
    """
    List workflow runs.

    Examples:

        # List all runs
        pyworkflow runs list

        # Search runs by workflow name or input
        pyworkflow runs list --query order

        # List failed runs
        pyworkflow runs list --status failed

        # List runs from today
        pyworkflow runs list --start-time 2025-01-01

        # List runs in a time range
        pyworkflow runs list --start-time 2025-01-01T00:00:00 --end-time 2025-01-02T00:00:00

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
        runs_list, _next_cursor = await storage.list_runs(
            query=query,
            status=status_filter,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

        if not runs_list:
            print_info("No workflow runs found")
            return

        # Calculate durations (stored as dynamic attribute for display)
        durations: dict[str, str] = {}
        for run in runs_list:
            if run.started_at and run.completed_at:
                dur = (run.completed_at - run.started_at).total_seconds()
                durations[run.run_id] = f"{dur:.1f}s"
            elif run.started_at:
                dur = (datetime.now() - run.started_at.replace(tzinfo=None)).total_seconds()
                durations[run.run_id] = f"{dur:.1f}s (ongoing)"
            else:
                durations[run.run_id] = "-"

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
                    "duration": durations.get(run.run_id, "-"),
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
                    "Started": run.started_at.strftime("%Y-%m-%d %H:%M:%S")
                    if run.started_at
                    else "-",
                    "Duration": durations.get(run.run_id, "-"),
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
                "context": run.context,
            }
            format_json(data)

        else:  # table or plain (use key-value format)
            data = {
                "Run ID": run.run_id,
                "Workflow": run.workflow_name,
                "Status": run.status.value,
                "Created": run.created_at.strftime("%Y-%m-%d %H:%M:%S") if run.created_at else "-",
                "Started": run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else "-",
                "Completed": run.completed_at.strftime("%Y-%m-%d %H:%M:%S")
                if run.completed_at
                else "-",
                "Duration": duration_str,
            }

            # Add input args if present
            if run.input_kwargs:
                try:
                    kwargs = json.loads(run.input_kwargs)
                    if kwargs:
                        data["Input Arguments"] = json.dumps(kwargs, indent=2)
                except Exception:
                    pass

            # Add result or error
            if run.result:
                try:
                    result = json.loads(run.result)
                    data["Result"] = (
                        json.dumps(result, indent=2) if not isinstance(result, str) else result
                    )
                except Exception:
                    data["Result"] = run.result

            if run.error:
                data["Error"] = run.error

            # Add context if present
            if run.context:
                data["Context"] = json.dumps(run.context, indent=2)

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
    event_filter: str | None,
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
            from pyworkflow.cli.output.styles import DIM, RESET, Colors

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
                    data_lines = data_str.split("\n")
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


@runs.command(name="cancel")
@click.argument("run_id")
@click.option(
    "--wait/--no-wait",
    default=False,
    help="Wait for cancellation to complete",
)
@click.option(
    "--timeout",
    type=int,
    default=30,
    help="Timeout in seconds when waiting (default: 30)",
)
@click.option(
    "--reason",
    help="Reason for cancellation",
)
@click.pass_context
@async_command
async def cancel_run(
    ctx: click.Context,
    run_id: str,
    wait: bool,
    timeout: int,
    reason: str | None,
) -> None:
    """
    Cancel a running or suspended workflow.

    Gracefully terminates workflow execution. The workflow will receive
    a CancellationError at the next checkpoint (step execution, sleep, or hook).

    Args:
        RUN_ID: Workflow run identifier

    Examples:

        # Cancel a workflow
        pyworkflow runs cancel run_abc123def456

        # Cancel and wait for completion
        pyworkflow runs cancel run_abc123def456 --wait

        # Cancel with timeout
        pyworkflow runs cancel run_abc123def456 --wait --timeout 60

        # Cancel with reason
        pyworkflow runs cancel run_abc123def456 --reason "User requested"
    """
    from pyworkflow.engine.executor import cancel_workflow

    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        # First check if workflow exists
        run = await storage.get_run(run_id)
        if not run:
            print_error(f"Workflow run '{run_id}' not found")
            raise click.Abort()

        # Check if already in terminal state
        terminal_states = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
        if run.status in terminal_states:
            print_warning(f"Workflow is already in terminal state: {run.status.value}")
            return

        # Cancel the workflow
        print_info(f"Cancelling workflow: {run_id}")

        cancelled = await cancel_workflow(
            run_id=run_id,
            reason=reason,
            wait=wait,
            timeout=float(timeout) if wait else None,
            storage=storage,
        )

        if cancelled:
            if wait:
                # Get updated status
                run = await storage.get_run(run_id)
                if run and run.status == RunStatus.CANCELLED:
                    print_success(f"Workflow cancelled successfully: {run_id}")
                else:
                    print_warning("Cancellation requested but workflow may still be running")
            else:
                print_success(f"Cancellation requested for workflow: {run_id}")
                print_info("Use --wait to wait for cancellation to complete")
        else:
            print_warning("Could not cancel workflow (may already be in terminal state)")

        # Output in different formats
        if output == "json":
            run = await storage.get_run(run_id)
            data = {
                "run_id": run_id,
                "cancelled": cancelled,
                "status": run.status.value if run else None,
            }
            format_json(data)

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Failed to cancel workflow: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@runs.command(name="children")
@click.argument("run_id")
@click.option(
    "--status",
    type=click.Choice([s.value for s in RunStatus], case_sensitive=False),
    help="Filter by child run status",
)
@click.pass_context
@async_command
async def list_children(
    ctx: click.Context,
    run_id: str,
    status: str | None,
) -> None:
    """
    List child workflows spawned by a parent workflow.

    Shows all child workflows that were started by the specified parent workflow
    using start_child_workflow(). Displays run_id, workflow name, status, and
    timing information for each child.

    Args:
        RUN_ID: Parent workflow run identifier

    Examples:

        # List all children of a workflow
        pyworkflow runs children run_abc123def456

        # List only running children
        pyworkflow runs children run_abc123def456 --status running

        # JSON output
        pyworkflow --output json runs children run_abc123def456
    """
    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        # Check if parent workflow exists
        parent_run = await storage.get_run(run_id)
        if not parent_run:
            print_error(f"Parent workflow run '{run_id}' not found")
            raise click.Abort()

        # Parse status filter
        status_filter = RunStatus(status) if status else None

        # Get children
        children = await storage.get_children(run_id, status=status_filter)

        if not children:
            print_info(f"No child workflows found for run: {run_id}")
            return

        def _calc_duration(child: WorkflowRun) -> str:
            """Calculate duration for display."""
            if child.started_at and child.completed_at:
                duration = (child.completed_at - child.started_at).total_seconds()
                return f"{duration:.1f}s"
            elif child.started_at:
                duration = (datetime.now() - child.started_at.replace(tzinfo=None)).total_seconds()
                return f"{duration:.1f}s (ongoing)"
            else:
                return "-"

        # Format output
        if output == "json":
            data = [
                {
                    "run_id": child.run_id,
                    "workflow_name": child.workflow_name,
                    "status": child.status.value,
                    "nesting_depth": child.nesting_depth,
                    "created_at": child.created_at.isoformat() if child.created_at else None,
                    "started_at": child.started_at.isoformat() if child.started_at else None,
                    "completed_at": child.completed_at.isoformat() if child.completed_at else None,
                    "duration": _calc_duration(child),
                }
                for child in children
            ]
            format_json(data)

        elif output == "plain":
            child_ids = [child.run_id for child in children]
            format_plain(child_ids)

        else:  # table
            data = [
                {
                    "Run ID": child.run_id,
                    "Workflow": child.workflow_name,
                    "Status": child.status.value,
                    "Depth": child.nesting_depth,
                    "Started": child.started_at.strftime("%Y-%m-%d %H:%M:%S")
                    if child.started_at
                    else "-",
                    "Duration": _calc_duration(child),
                }
                for child in children
            ]
            format_table(
                data,
                ["Run ID", "Workflow", "Status", "Depth", "Started", "Duration"],
                title=f"Child Workflows of {run_id}",
            )

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Failed to list child workflows: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@runs.command(name="chain")
@click.argument("run_id")
@click.pass_context
@async_command
async def run_chain(
    ctx: click.Context,
    run_id: str,
) -> None:
    """
    Show the continue-as-new chain for a workflow run.

    Displays all workflow runs in a continue-as-new chain, from the original
    run to the latest continuation. Useful for tracking long-running workflows
    that use continue_as_new() to reset their event history.

    Args:
        RUN_ID: Any workflow run identifier in the chain

    Examples:

        # Show chain for a workflow
        pyworkflow runs chain run_abc123def456

        # JSON output
        pyworkflow --output json runs chain run_abc123def456
    """
    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        # Get the chain
        chain = await storage.get_workflow_chain(run_id)

        if not chain:
            print_error(f"Workflow run '{run_id}' not found")
            raise click.Abort()

        def _calc_duration(run: WorkflowRun) -> str:
            """Calculate duration for display."""
            if run.started_at and run.completed_at:
                duration = (run.completed_at - run.started_at).total_seconds()
                return f"{duration:.1f}s"
            elif run.started_at:
                duration = (datetime.now() - run.started_at.replace(tzinfo=None)).total_seconds()
                return f"{duration:.1f}s (ongoing)"
            else:
                return "-"

        # Format output
        if output == "json":
            data = [
                {
                    "run_id": run.run_id,
                    "workflow_name": run.workflow_name,
                    "status": run.status.value,
                    "continued_from_run_id": run.continued_from_run_id,
                    "continued_to_run_id": run.continued_to_run_id,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    "duration": _calc_duration(run),
                }
                for run in chain
            ]
            format_json(data)

        elif output == "plain":
            run_ids = [run.run_id for run in chain]
            format_plain(run_ids)

        else:  # table
            from pyworkflow.cli.output.styles import DIM, RESET, Colors

            print(f"\n{Colors.PRIMARY}{Colors.bold('Continue-As-New Chain')}{RESET}")
            print(f"{DIM}{'─' * 60}{RESET}")
            print(f"Chain length: {len(chain)} run(s)\n")

            for i, run in enumerate(chain):
                # Indicate position in chain
                if i == 0:
                    position = "START"
                elif i == len(chain) - 1:
                    position = "CURRENT"
                else:
                    position = f"#{i + 1}"

                # Color code status
                status_color = {
                    "completed": Colors.GREEN,
                    "failed": Colors.RED,
                    "running": Colors.BLUE,
                    "suspended": Colors.YELLOW,
                    "cancelled": Colors.RED,
                    "continued_as_new": Colors.CYAN,
                }.get(run.status.value, "")

                # Mark the queried run
                marker = " <--" if run.run_id == run_id else ""

                print(f"{Colors.bold(position)}{marker}")
                print(f"   Run ID: {run.run_id}")
                print(f"   Workflow: {run.workflow_name}")
                print(f"   Status: {status_color}{run.status.value}{RESET}")
                print(f"   Duration: {_calc_duration(run)}")

                if run.started_at:
                    print(f"   Started: {run.started_at.strftime('%Y-%m-%d %H:%M:%S')}")

                # Show arrow to next run if not last
                if i < len(chain) - 1:
                    print(f"\n   {DIM}↓ continued as new{RESET}\n")
                else:
                    print()

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Failed to get workflow chain: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()
