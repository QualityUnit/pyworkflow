"""PyWorkflow CLI - Manage and run durable workflows."""

from typing import Optional

import click
from loguru import logger

from pyworkflow import __version__
from pyworkflow.cli.utils.config import load_config
from pyworkflow.cli.utils.discovery import discover_workflows
from pyworkflow.cli.utils.storage import create_storage


@click.group()
@click.version_option(version=__version__, prog_name="pyworkflow")
@click.option(
    "--module",
    envvar="PYWORKFLOW_MODULE",
    help="Python module to import for workflow discovery",
)
@click.option(
    "--runtime",
    type=click.Choice(["local", "celery"], case_sensitive=False),
    envvar="PYWORKFLOW_RUNTIME",
    default="celery",
    help="Execution runtime: local (in-process) or celery (distributed workers). Default: celery",
)
@click.option(
    "--storage",
    type=click.Choice(
        ["file", "memory", "sqlite", "postgres", "mysql", "dynamodb", "cassandra"],
        case_sensitive=False,
    ),
    envvar="PYWORKFLOW_STORAGE_BACKEND",
    help="Storage backend type (default: file)",
)
@click.option(
    "--storage-path",
    envvar="PYWORKFLOW_STORAGE_PATH",
    help="Storage path for file backend (default: ./workflow_data)",
)
@click.option(
    "--output",
    type=click.Choice(["table", "json", "plain"], case_sensitive=False),
    default="table",
    help="Output format (default: table)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
@click.pass_context
def main(
    ctx: click.Context,
    module: str | None,
    runtime: str,
    storage: str | None,
    storage_path: str | None,
    output: str,
    verbose: bool,
) -> None:
    """
    PyWorkflow CLI - Manage and run durable workflows.

    PyWorkflow enables fault-tolerant, long-running workflows with automatic
    retry, sleep/delay capabilities, and webhook integration.

    Examples:

        # List all registered workflows
        pyworkflow --module myapp.workflows workflows list

        # Run a workflow
        pyworkflow --module myapp.workflows workflows run my_workflow

        # Check workflow run status
        pyworkflow runs status run_abc123

        # View workflow execution logs
        pyworkflow runs logs run_abc123

    Configuration:

        You can configure PyWorkflow via:
        - CLI flags (highest priority)
        - Environment variables (PYWORKFLOW_MODULE, PYWORKFLOW_STORAGE_BACKEND, etc.)
        - Config file (pyworkflow.toml or pyproject.toml)

    For more information, visit: https://github.com/yourusername/pyworkflow
    """
    # Configure logging
    if verbose:
        logger.enable("pyworkflow")
        logger.info("Verbose logging enabled")
    else:
        logger.disable("pyworkflow")

    # Load configuration from file
    config = load_config()

    # Store configuration in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["module"] = module
    ctx.obj["runtime"] = runtime
    ctx.obj["storage_type"] = storage
    ctx.obj["storage_path"] = storage_path
    ctx.obj["output"] = output
    ctx.obj["config"] = config
    ctx.obj["verbose"] = verbose


# Import and register commands
from pyworkflow.cli.commands.hooks import hooks
from pyworkflow.cli.commands.quickstart import quickstart
from pyworkflow.cli.commands.runs import runs
from pyworkflow.cli.commands.scheduler import scheduler
from pyworkflow.cli.commands.schedules import schedules
from pyworkflow.cli.commands.setup import setup
from pyworkflow.cli.commands.worker import worker
from pyworkflow.cli.commands.workflows import workflows

main.add_command(workflows)
main.add_command(runs)
main.add_command(schedules)
main.add_command(scheduler)
main.add_command(worker)
main.add_command(setup)
main.add_command(quickstart)
main.add_command(hooks)


# Export main for entry point
__all__ = ["main"]
