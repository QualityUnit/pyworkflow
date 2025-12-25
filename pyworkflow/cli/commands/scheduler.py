"""CLI commands for running the local scheduler."""

import signal
import sys

import click

from pyworkflow.cli.utils.async_helpers import async_command


@click.group()
def scheduler():
    """
    Run the schedule executor.

    The scheduler polls storage for due schedules and triggers workflows.
    Use this command when running with local runtime (no Celery).

    For Celery runtime, use 'celery beat' instead:

        celery -A pyworkflow.celery.app beat \\
            --scheduler pyworkflow.celery.scheduler:PyWorkflowScheduler
    """
    pass


@scheduler.command("run")
@click.option(
    "--poll-interval",
    type=float,
    default=5.0,
    help="Seconds between storage polls (default: 5.0)",
)
@click.option(
    "--duration",
    type=float,
    default=None,
    help="Run for specified seconds then exit (default: run forever)",
)
@click.pass_context
@async_command
async def run_scheduler(ctx: click.Context, poll_interval: float, duration: float | None) -> None:
    """
    Run the local scheduler.

    This polls storage for due schedules and triggers them using
    the configured runtime. Use this when running with local runtime.

    For Celery runtime, use 'celery beat' instead.

    Examples:

        # Run scheduler with default settings
        pyworkflow scheduler run

        # Custom poll interval
        pyworkflow scheduler run --poll-interval 10

        # Run for 60 seconds (useful for testing)
        pyworkflow scheduler run --duration 60

        # With a specific module
        pyworkflow --module myapp.workflows scheduler run
    """
    from pyworkflow.cli.utils.discovery import discover_workflows
    from pyworkflow.cli.utils.storage import create_storage
    from pyworkflow.config import configure, reset_config
    from pyworkflow.scheduler import LocalScheduler

    # Get config from context
    module = ctx.obj.get("module")
    storage_type = ctx.obj.get("storage_type")
    storage_path = ctx.obj.get("storage_path")
    runtime = ctx.obj.get("runtime", "local")

    # Discover workflows if module specified
    if module:
        click.echo(f"Discovering workflows from: {module}")
        try:
            discover_workflows(module)
        except Exception as e:
            raise click.ClickException(f"Failed to discover workflows: {e}")

    # Create storage backend
    try:
        storage = create_storage(storage_type, storage_path)
    except Exception as e:
        raise click.ClickException(f"Failed to create storage: {e}")

    # Configure pyworkflow
    reset_config()
    configure(
        storage=storage,
        default_runtime=runtime,
        default_durable=True,
    )

    # Create and run scheduler
    local_scheduler = LocalScheduler(
        storage=storage,
        poll_interval=poll_interval,
    )

    click.echo("Starting local scheduler...")
    click.echo(f"  Poll interval: {poll_interval}s")
    click.echo(f"  Runtime: {runtime}")
    if duration:
        click.echo(f"  Duration: {duration}s")
    else:
        click.echo("  Duration: indefinite (Ctrl+C to stop)")
    click.echo()

    # Handle graceful shutdown
    def signal_handler(signum, frame):
        click.echo("\nReceived shutdown signal, stopping scheduler...")
        local_scheduler.stop()

    # Register signal handlers
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        await local_scheduler.run(duration=duration)
    except KeyboardInterrupt:
        click.echo("\nScheduler stopped by user")
    except Exception as e:
        raise click.ClickException(f"Scheduler error: {e}")

    click.echo("Scheduler stopped")
