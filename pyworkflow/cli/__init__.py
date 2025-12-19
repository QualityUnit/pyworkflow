"""PyWorkflow CLI - Manage and run durable workflows."""

import click
from typing import Optional

from pyworkflow import __version__
from pyworkflow.cli.utils.config import load_config
from pyworkflow.cli.utils.discovery import discover_workflows
from pyworkflow.cli.utils.storage import create_storage
from loguru import logger


@click.group()
@click.version_option(version=__version__, prog_name="pyworkflow")
@click.option(
    "--module",
    envvar="PYWORKFLOW_MODULE",
    help="Python module to import for workflow discovery",
)
@click.option(
    "--storage",
    type=click.Choice(["file", "memory"], case_sensitive=False),
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
    module: Optional[str],
    storage: Optional[str],
    storage_path: Optional[str],
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
    ctx.obj["storage_type"] = storage
    ctx.obj["storage_path"] = storage_path
    ctx.obj["output"] = output
    ctx.obj["config"] = config
    ctx.obj["verbose"] = verbose


# Import and register commands
from pyworkflow.cli.commands.workflows import workflows
from pyworkflow.cli.commands.runs import runs

main.add_command(workflows)
main.add_command(runs)


# Export main for entry point
__all__ = ["main"]
