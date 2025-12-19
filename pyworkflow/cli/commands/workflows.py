"""Workflow management commands."""

import json
import click
from typing import Optional

import pyworkflow
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
)


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
@click.argument("workflow_name")
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
@click.pass_context
@async_command
async def run_workflow(
    ctx: click.Context,
    workflow_name: str,
    arg: tuple,
    args_json: Optional[str],
    durable: bool,
    idempotency_key: Optional[str],
) -> None:
    """
    Execute a workflow.

    Args:
        WORKFLOW_NAME: Name of the workflow to run

    Examples:

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
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Discover workflows
    discover_workflows(module, config)

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

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Execute workflow
    print_info(f"Starting workflow: {workflow_name}")
    if kwargs:
        print_info(f"Arguments: {json.dumps(kwargs, indent=2)}")

    try:
        run_id = await pyworkflow.start(
            workflow_meta.func,
            **kwargs,
            durable=durable,
            storage=storage,
            idempotency_key=idempotency_key,
        )

        # Format output
        if output == "json":
            format_json({"run_id": run_id, "workflow_name": workflow_name})
        else:
            print_success(f"Workflow started successfully")
            print_info(f"Run ID: {run_id}")

            if durable:
                print_info(f"\nCheck status with: pyworkflow runs status {run_id}")
                print_info(f"View logs with: pyworkflow runs logs {run_id}")

    except Exception as e:
        print_error(f"Failed to start workflow: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()
