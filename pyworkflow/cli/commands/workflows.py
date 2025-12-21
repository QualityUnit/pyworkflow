"""Workflow management commands."""

import asyncio
import inspect
import json
import click
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, get_type_hints

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.table import Table
from rich.text import Text

import pyworkflow
from pyworkflow import RunStatus
from pyworkflow.cli.utils.async_helpers import async_command
from pyworkflow.cli.utils.discovery import discover_workflows
from pyworkflow.cli.utils.storage import create_storage
from pyworkflow.cli.output.formatters import (
    format_table,
    format_json,
    format_plain,
    format_key_value,
    print_success,
    print_error,
    print_info,
    print_warning,
)

console = Console()


def _select_workflow(workflows_dict: Dict[str, Any]) -> Optional[str]:
    """
    Display an interactive workflow selection menu.

    Args:
        workflows_dict: Dictionary of workflow name -> WorkflowMetadata

    Returns:
        Selected workflow name or None if cancelled
    """
    if not workflows_dict:
        print_error("No workflows registered")
        return None

    workflow_names = list(workflows_dict.keys())

    # Display selection table
    table = Table(title="Select a Workflow", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Workflow Name", style="green")
    table.add_column("Description", style="dim")

    for idx, name in enumerate(workflow_names, 1):
        meta = workflows_dict[name]
        description = ""
        if meta.original_func.__doc__:
            # Get first line of docstring
            description = meta.original_func.__doc__.strip().split("\n")[0][:60]
        table.add_row(str(idx), name, description or "-")

    console.print(table)
    console.print()

    # Prompt for selection
    while True:
        try:
            choice = IntPrompt.ask(
                "Enter workflow number",
                default=1,
                show_default=True,
            )
            if 1 <= choice <= len(workflow_names):
                return workflow_names[choice - 1]
            else:
                print_error(f"Please enter a number between 1 and {len(workflow_names)}")
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled[/dim]")
            return None


def _get_workflow_parameters(func: Any) -> List[Dict[str, Any]]:
    """
    Extract parameter information from a workflow function.

    Args:
        func: The workflow function to inspect

    Returns:
        List of parameter dicts with name, type, default, and required info
    """
    sig = inspect.signature(func)
    params = []

    # Try to get type hints
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    for param_name, param in sig.parameters.items():
        # Skip *args and **kwargs
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        param_info = {
            "name": param_name,
            "type": hints.get(param_name, Any),
            "has_default": param.default is not inspect.Parameter.empty,
            "default": param.default if param.default is not inspect.Parameter.empty else None,
            "required": param.default is inspect.Parameter.empty,
        }
        params.append(param_info)

    return params


def _get_type_name(type_hint: Any) -> str:
    """Get a human-readable name for a type hint."""
    if type_hint is Any:
        return "any"
    if hasattr(type_hint, "__name__"):
        return type_hint.__name__
    return str(type_hint)


def _parse_value(value_str: str, type_hint: Any) -> Any:
    """
    Parse a string value to the appropriate type.

    Args:
        value_str: The string value from user input
        type_hint: The expected type

    Returns:
        Parsed value
    """
    if not value_str:
        return None

    # Handle common types
    if type_hint is bool or (hasattr(type_hint, "__name__") and type_hint.__name__ == "bool"):
        return value_str.lower() in ("true", "1", "yes", "y")

    if type_hint is int or (hasattr(type_hint, "__name__") and type_hint.__name__ == "int"):
        return int(value_str)

    if type_hint is float or (hasattr(type_hint, "__name__") and type_hint.__name__ == "float"):
        return float(value_str)

    # Try JSON parsing for complex types (lists, dicts, etc.)
    try:
        return json.loads(value_str)
    except json.JSONDecodeError:
        # Return as string
        return value_str


def _prompt_for_arguments(params: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Interactively prompt user for workflow argument values.

    Args:
        params: List of parameter info dicts

    Returns:
        Dictionary of argument name -> value
    """
    if not params:
        return {}

    console.print("\n[bold cyan]Workflow Arguments[/bold cyan]")
    console.print("[dim]Enter values for each argument (press Enter for default)[/dim]\n")

    kwargs = {}

    for param in params:
        name = param["name"]
        type_hint = param["type"]
        has_default = param["has_default"]
        default = param["default"]
        required = param["required"]

        type_name = _get_type_name(type_hint)

        # Build prompt string
        if required:
            prompt_text = f"[green]{name}[/green] [dim]({type_name})[/dim]"
        else:
            default_display = repr(default) if default is not None else "None"
            prompt_text = f"[green]{name}[/green] [dim]({type_name}, default={default_display})[/dim]"

        # Handle boolean type specially
        if type_hint is bool or (hasattr(type_hint, "__name__") and type_hint.__name__ == "bool"):
            if has_default:
                value = Confirm.ask(prompt_text, default=default)
            else:
                value = Confirm.ask(prompt_text, default=False)
            kwargs[name] = value
        else:
            # Standard text prompt
            if has_default and default is not None:
                default_str = json.dumps(default) if not isinstance(default, str) else default
                value_str = Prompt.ask(prompt_text, default=default_str)
            else:
                value_str = Prompt.ask(prompt_text, default="" if not required else None)

            if value_str == "" and has_default:
                kwargs[name] = default
            elif value_str == "" and not required:
                # Skip optional params with no input
                continue
            elif value_str is not None:
                kwargs[name] = _parse_value(value_str, type_hint)

    return kwargs


def _format_event_type(event_type: str) -> Text:
    """Format event type with appropriate color."""
    colors = {
        "workflow_started": "blue",
        "workflow_completed": "green",
        "workflow_failed": "red",
        "step_started": "cyan",
        "step_completed": "green",
        "step_failed": "red",
        "step_retrying": "yellow",
        "sleep_started": "magenta",
        "sleep_completed": "magenta",
        "hook_created": "yellow",
        "hook_received": "green",
    }
    color = colors.get(event_type, "white")
    return Text(event_type, style=color)


def _format_status(status: RunStatus) -> Text:
    """Format run status with appropriate color."""
    colors = {
        RunStatus.PENDING: "dim",
        RunStatus.RUNNING: "blue",
        RunStatus.SUSPENDED: "yellow",
        RunStatus.COMPLETED: "green",
        RunStatus.FAILED: "red",
        RunStatus.CANCELLED: "dim",
    }
    color = colors.get(status, "white")
    return Text(status.value.upper(), style=f"bold {color}")


def _build_watch_display(
    workflow_name: str,
    run_id: str,
    status: RunStatus,
    events: List[Any],
    start_time: datetime,
) -> Panel:
    """Build the display panel for watch mode."""
    # Calculate elapsed time
    elapsed = (datetime.now() - start_time).total_seconds()
    elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s" if elapsed >= 60 else f"{elapsed:.1f}s"

    # Build header
    header = Table.grid(padding=(0, 2))
    header.add_column()
    header.add_column()
    header.add_column()
    header.add_column()

    status_text = _format_status(status)
    header.add_row(
        Text("Workflow: ", style="dim") + Text(workflow_name, style="bold"),
        Text("Status: ", style="dim") + status_text,
        Text("Elapsed: ", style="dim") + Text(elapsed_str),
        Text("Events: ", style="dim") + Text(str(len(events))),
    )

    # Build events table (show last 10 events)
    events_table = Table(
        show_header=True,
        header_style="bold dim",
        box=None,
        padding=(0, 1),
        expand=True,
    )
    events_table.add_column("Time", style="dim", width=12)
    events_table.add_column("Event", width=20)
    events_table.add_column("Details", ratio=1)

    # Show most recent events (last 10)
    recent_events = events[-10:] if len(events) > 10 else events
    for event in recent_events:
        time_str = event.timestamp.strftime("%H:%M:%S") if event.timestamp else "-"
        event_type = _format_event_type(event.type.value)

        # Extract key details from event data
        details = ""
        if event.data:
            if "step_name" in event.data:
                details = f"step: {event.data['step_name']}"
            elif "step_id" in event.data:
                details = f"step_id: {event.data['step_id'][:20]}..."
            elif "sleep_id" in event.data:
                details = f"sleep: {event.data['sleep_id']}"
            elif "error" in event.data:
                details = f"error: {event.data['error'][:40]}..."
            elif "result" in event.data:
                result_str = str(event.data["result"])[:40]
                details = f"result: {result_str}..."

        events_table.add_row(time_str, event_type, details)

    # Combine into a layout
    layout = Table.grid(expand=True)
    layout.add_row(header)
    layout.add_row(Text(""))  # Spacer
    layout.add_row(events_table)

    # Add footer based on status
    if status == RunStatus.SUSPENDED:
        layout.add_row(Text(""))
        layout.add_row(Text("Workflow suspended (waiting for sleep/hook)...", style="dim italic"))
    elif status == RunStatus.RUNNING:
        layout.add_row(Text(""))
        layout.add_row(Text("Workflow running...", style="dim italic"))

    return Panel(
        layout,
        title=f"[bold]Workflow Run: {run_id}[/bold]",
        border_style="blue" if status == RunStatus.RUNNING else (
            "green" if status == RunStatus.COMPLETED else (
                "red" if status == RunStatus.FAILED else "yellow"
            )
        ),
    )


async def _watch_workflow(
    run_id: str,
    workflow_name: str,
    storage: Any,
    poll_interval: float = 1.0,
    max_wait_for_start: float = 30.0,
) -> RunStatus:
    """
    Watch a workflow execution in real-time.

    Polls for events and status, displaying updates until the workflow
    completes, fails, or is cancelled.

    Args:
        run_id: Workflow run ID
        workflow_name: Name of the workflow
        storage: Storage backend
        poll_interval: Seconds between polls
        max_wait_for_start: Max seconds to wait for run to be created

    Returns:
        Final workflow status
    """
    start_time = datetime.now()
    seen_event_ids: Set[str] = set()
    all_events: List[Any] = []

    terminal_statuses = {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }

    # Wait for the run to be created (with Celery, the worker creates it)
    run = None
    wait_start = datetime.now()
    while run is None:
        run = await pyworkflow.get_workflow_run(run_id, storage=storage)
        if run is None:
            elapsed = (datetime.now() - wait_start).total_seconds()
            if elapsed > max_wait_for_start:
                print_error(f"Timeout waiting for workflow run to be created")
                print_info("Make sure Celery workers are running: pyworkflow worker run")
                return RunStatus.FAILED
            # Show waiting message
            console.print(f"[dim]Waiting for worker to start workflow... ({elapsed:.0f}s)[/dim]", end="\r")
            await asyncio.sleep(poll_interval)

    # Clear the waiting line
    console.print(" " * 60, end="\r")

    with Live(console=console, refresh_per_second=2) as live:
        while True:
            try:
                # Fetch current status
                run = await pyworkflow.get_workflow_run(run_id, storage=storage)
                if not run:
                    print_error(f"Workflow run '{run_id}' not found")
                    return RunStatus.FAILED

                status = run.status

                # Fetch events
                events = await pyworkflow.get_workflow_events(run_id, storage=storage)

                # Track new events
                for event in events:
                    if event.event_id not in seen_event_ids:
                        seen_event_ids.add(event.event_id)
                        all_events.append(event)

                # Sort events by sequence
                all_events.sort(key=lambda e: e.sequence or 0)

                # Update display
                panel = _build_watch_display(
                    workflow_name=workflow_name,
                    run_id=run_id,
                    status=status,
                    events=all_events,
                    start_time=start_time,
                )
                live.update(panel)

                # Check if workflow is done
                if status in terminal_statuses:
                    # Give a moment for final display
                    await asyncio.sleep(0.5)
                    return status

                # Wait before next poll
                await asyncio.sleep(poll_interval)

            except KeyboardInterrupt:
                console.print("\n[dim]Watch interrupted[/dim]")
                return RunStatus.RUNNING
            except Exception as e:
                console.print(f"\n[red]Error watching workflow: {e}[/red]")
                return RunStatus.FAILED


@click.group(name="workflows")
def workflows() -> None:
    """Manage workflows (list, info, run)."""
    pass


@workflows.command(name="list")
@click.pass_context
def list_workflows_cmd(ctx: click.Context) -> None:
    """
    List all registered workflows.

    Examples:

        # List workflows from a specific module
        pyworkflow --module myapp.workflows workflows list

        # List workflows with JSON output
        pyworkflow --module myapp.workflows --output json workflows list
    """
    # Get context data
    module = ctx.obj["module"]
    config = ctx.obj["config"]
    output = ctx.obj["output"]

    # Discover workflows
    discover_workflows(module, config)

    # Get registered workflows
    workflows_dict = pyworkflow.list_workflows()

    if not workflows_dict:
        print_info("No workflows registered")
        return

    # Format output
    if output == "json":
        data = [
            {
                "name": name,
                "max_duration": meta.max_duration or "None",
                "metadata": meta.metadata,
            }
            for name, meta in workflows_dict.items()
        ]
        format_json(data)

    elif output == "plain":
        names = list(workflows_dict.keys())
        format_plain(names)

    else:  # table
        data = [
            {
                "Name": name,
                "Max Duration": meta.max_duration or "-",
                "Metadata": json.dumps(meta.metadata) if meta.metadata else "-",
            }
            for name, meta in workflows_dict.items()
        ]
        format_table(data, ["Name", "Max Duration", "Metadata"], title="Registered Workflows")


@workflows.command(name="info")
@click.argument("workflow_name")
@click.pass_context
def workflow_info(ctx: click.Context, workflow_name: str) -> None:
    """
    Show detailed information about a workflow.

    Args:
        WORKFLOW_NAME: Name of the workflow to inspect

    Examples:

        pyworkflow --module myapp.workflows workflows info my_workflow
    """
    # Get context data
    module = ctx.obj["module"]
    config = ctx.obj["config"]
    output = ctx.obj["output"]

    # Discover workflows
    discover_workflows(module, config)

    # Get workflow metadata
    workflow_meta = pyworkflow.get_workflow(workflow_name)

    if not workflow_meta:
        print_error(f"Workflow '{workflow_name}' not found")
        raise click.Abort()

    # Format output
    if output == "json":
        data = {
            "name": workflow_meta.name,
            "max_duration": workflow_meta.max_duration,
            "metadata": workflow_meta.metadata,
            "function": {
                "name": workflow_meta.original_func.__name__,
                "module": workflow_meta.original_func.__module__,
                "doc": workflow_meta.original_func.__doc__,
            },
        }
        format_json(data)

    else:  # table or plain (use key-value format)
        data = {
            "Name": workflow_meta.name,
            "Max Duration": workflow_meta.max_duration or "None",
            "Function": workflow_meta.original_func.__name__,
            "Module": workflow_meta.original_func.__module__,
            "Metadata": json.dumps(workflow_meta.metadata, indent=2) if workflow_meta.metadata else "{}",
        }

        if workflow_meta.original_func.__doc__:
            data["Description"] = workflow_meta.original_func.__doc__.strip()

        format_key_value(data, title=f"Workflow: {workflow_name}")


@workflows.command(name="run")
@click.argument("workflow_name", required=False)
@click.option(
    "--arg",
    multiple=True,
    help="Workflow argument in key=value format (can be repeated)",
)
@click.option(
    "--args-json",
    help="Workflow arguments as JSON string",
)
@click.option(
    "--durable/--no-durable",
    default=True,
    help="Run workflow in durable mode (default: durable)",
)
@click.option(
    "--idempotency-key",
    help="Idempotency key for workflow execution",
)
@click.option(
    "--no-wait",
    is_flag=True,
    default=False,
    help="Don't wait for workflow completion (just start and exit)",
)
@click.pass_context
@async_command
async def run_workflow(
    ctx: click.Context,
    workflow_name: Optional[str],
    arg: tuple,
    args_json: Optional[str],
    durable: bool,
    idempotency_key: Optional[str],
    no_wait: bool,
) -> None:
    """
    Execute a workflow and watch its progress.

    By default, waits for the workflow to complete, showing real-time events.
    Use --no-wait to start the workflow and exit immediately.

    When run without arguments, displays an interactive menu to select a workflow
    and prompts for any required arguments.

    Args:
        WORKFLOW_NAME: Name of the workflow to run (optional, will prompt if not provided)

    Examples:

        # Interactive mode - select workflow and enter arguments
        pyworkflow --module myapp.workflows workflows run

        # Run workflow with arguments
        pyworkflow --module myapp.workflows workflows run my_workflow \\
            --arg name=John --arg age=30

        # Run workflow with JSON arguments
        pyworkflow --module myapp.workflows workflows run my_workflow \\
            --args-json '{"name": "John", "age": 30}'

        # Run transient workflow
        pyworkflow --module myapp.workflows workflows run my_workflow \\
            --no-durable

        # Run with idempotency key
        pyworkflow --module myapp.workflows workflows run my_workflow \\
            --idempotency-key unique-operation-id
    """
    # Get context data
    module = ctx.obj["module"]
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    runtime_name = ctx.obj.get("runtime", "celery")
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Discover workflows
    discover_workflows(module, config)

    # Get registered workflows
    workflows_dict = pyworkflow.list_workflows()

    # Interactive mode: select workflow if not provided
    if not workflow_name:
        if not workflows_dict:
            print_error("No workflows registered")
            raise click.Abort()

        workflow_name = _select_workflow(workflows_dict)
        if not workflow_name:
            raise click.Abort()

    # Get workflow metadata
    workflow_meta = pyworkflow.get_workflow(workflow_name)

    if not workflow_meta:
        print_error(f"Workflow '{workflow_name}' not found")
        raise click.Abort()

    # Parse arguments
    kwargs = {}

    # Parse --arg flags
    for arg_pair in arg:
        if "=" not in arg_pair:
            print_error(f"Invalid argument format: {arg_pair}. Expected key=value")
            raise click.Abort()

        key, value = arg_pair.split("=", 1)

        # Try to parse as JSON, fall back to string
        try:
            kwargs[key] = json.loads(value)
        except json.JSONDecodeError:
            kwargs[key] = value

    # Parse --args-json
    if args_json:
        try:
            json_args = json.loads(args_json)
            if not isinstance(json_args, dict):
                print_error("--args-json must be a JSON object")
                raise click.Abort()
            kwargs.update(json_args)
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON in --args-json: {e}")
            raise click.Abort()

    # Interactive mode: prompt for arguments if none provided
    if not kwargs and not arg and not args_json:
        params = _get_workflow_parameters(workflow_meta.original_func)
        if params:
            prompted_kwargs = _prompt_for_arguments(params)
            kwargs.update(prompted_kwargs)
            console.print()  # Add spacing after prompts

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Execute workflow
    print_info(f"Starting workflow: {workflow_name}")
    print_info(f"Runtime: {runtime_name}")
    if kwargs:
        print_info(f"Arguments: {json.dumps(kwargs, indent=2)}")

    # Celery runtime requires durable mode
    if runtime_name == "celery" and not durable:
        print_error("Celery runtime requires durable mode. Use --durable or --runtime local")
        raise click.Abort()

    try:
        run_id = await pyworkflow.start(
            workflow_meta.func,
            **kwargs,
            runtime=runtime_name,
            durable=durable,
            storage=storage,
            idempotency_key=idempotency_key,
        )

        # JSON output mode - just output and exit
        if output == "json":
            format_json({"run_id": run_id, "workflow_name": workflow_name, "runtime": runtime_name})
            return

        # No-wait mode - start and exit immediately
        if no_wait:
            print_success("Workflow started successfully")
            print_info(f"Run ID: {run_id}")
            print_info(f"Runtime: {runtime_name}")

            if durable:
                print_info(f"\nCheck status with: pyworkflow runs status {run_id}")
                print_info(f"View logs with: pyworkflow runs logs {run_id}")

            if runtime_name == "celery":
                print_info("\nNote: Workflow dispatched to Celery workers.")
                print_info("Ensure workers are running: pyworkflow worker run")
            return

        # Watch mode (default) - poll and display events until completion
        console.print(f"[dim]Started workflow run: {run_id}[/dim]")
        console.print(f"[dim]Watching for events... (Ctrl+C to stop watching)[/dim]\n")

        # Wait a moment for initial events to be recorded
        await asyncio.sleep(0.5)

        # Watch the workflow
        final_status = await _watch_workflow(
            run_id=run_id,
            workflow_name=workflow_name,
            storage=storage,
            poll_interval=1.0,
        )

        # Print final summary
        console.print()
        if final_status == RunStatus.COMPLETED:
            print_success(f"Workflow completed successfully")
            # Fetch and show result
            run = await pyworkflow.get_workflow_run(run_id, storage=storage)
            if run and run.result:
                try:
                    result = json.loads(run.result)
                    console.print(f"[dim]Result:[/dim] {json.dumps(result, indent=2)}")
                except json.JSONDecodeError:
                    console.print(f"[dim]Result:[/dim] {run.result}")
        elif final_status == RunStatus.FAILED:
            print_error("Workflow failed")
            run = await pyworkflow.get_workflow_run(run_id, storage=storage)
            if run and run.error:
                console.print(f"[red]Error:[/red] {run.error}")
            raise click.Abort()
        elif final_status == RunStatus.CANCELLED:
            print_warning("Workflow was cancelled")
        else:
            # Still running (user interrupted watch)
            print_info(f"Workflow still running. Check status with: pyworkflow runs status {run_id}")

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Failed to start workflow: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()
