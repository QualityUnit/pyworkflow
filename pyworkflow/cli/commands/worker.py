"""Worker management commands for Celery runtime."""

import os
import sys
import click
from typing import Optional

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


@click.group(name="worker")
def worker() -> None:
    """Manage Celery workers for workflow execution."""
    pass


@worker.command(name="run")
@click.option(
    "--workflow",
    "queue_workflow",
    is_flag=True,
    help="Only process workflow orchestration tasks (pyworkflow.workflows queue)",
)
@click.option(
    "--step",
    "queue_step",
    is_flag=True,
    help="Only process step execution tasks (pyworkflow.steps queue)",
)
@click.option(
    "--schedule",
    "queue_schedule",
    is_flag=True,
    help="Only process scheduled resumption tasks (pyworkflow.schedules queue)",
)
@click.option(
    "--concurrency",
    "-c",
    type=int,
    default=None,
    help="Number of worker processes (default: auto-detect)",
)
@click.option(
    "--loglevel",
    "-l",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default="info",
    help="Log level for the worker (default: info)",
)
@click.option(
    "--hostname",
    "-n",
    default=None,
    help="Worker hostname (default: auto-generated)",
)
@click.option(
    "--beat",
    is_flag=True,
    help="Also start Celery Beat scheduler for periodic tasks",
)
@click.pass_context
def run_worker(
    ctx: click.Context,
    queue_workflow: bool,
    queue_step: bool,
    queue_schedule: bool,
    concurrency: Optional[int],
    loglevel: str,
    hostname: Optional[str],
    beat: bool,
) -> None:
    """
    Start a Celery worker for processing workflows.

    By default, processes all queues. Use --workflow, --step, or --schedule
    flags to limit to specific queue types.

    Examples:

        # Start a worker processing all queues
        pyworkflow worker run

        # Start a workflow orchestration worker only
        pyworkflow worker run --workflow

        # Start a step execution worker (for heavy computation)
        pyworkflow worker run --step --concurrency 4

        # Start a schedule worker (for sleep resumption)
        pyworkflow worker run --schedule

        # Start with beat scheduler
        pyworkflow worker run --beat

        # Start with custom log level
        pyworkflow worker run --loglevel debug
    """
    # Get config
    config = ctx.obj.get("config", {})
    module = ctx.obj.get("module")

    # Determine queues to process
    queues = []
    if queue_workflow:
        queues.append("pyworkflow.workflows")
    if queue_step:
        queues.append("pyworkflow.steps")
    if queue_schedule:
        queues.append("pyworkflow.schedules")

    # If no specific queue selected, process all
    if not queues:
        queues = [
            "pyworkflow.default",
            "pyworkflow.workflows",
            "pyworkflow.steps",
            "pyworkflow.schedules",
        ]

    # Get broker config from config file or environment
    celery_config = config.get("celery", {})
    broker_url = celery_config.get(
        "broker",
        os.getenv("PYWORKFLOW_CELERY_BROKER", "redis://localhost:6379/0"),
    )
    result_backend = celery_config.get(
        "result_backend",
        os.getenv("PYWORKFLOW_CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    )

    # Set environment for workflow discovery
    if module:
        os.environ["PYWORKFLOW_DISCOVER"] = module

    print_info("Starting Celery worker...")
    print_info(f"Broker: {broker_url}")
    print_info(f"Queues: {', '.join(queues)}")

    if concurrency:
        print_info(f"Concurrency: {concurrency}")

    try:
        # Import and configure Celery app
        from pyworkflow.celery.app import create_celery_app, discover_workflows

        # Create or get Celery app with configured broker
        app = create_celery_app(
            broker_url=broker_url,
            result_backend=result_backend,
        )

        # Configure worker arguments
        worker_args = [
            "worker",
            f"--loglevel={loglevel.upper()}",
            f"--queues={','.join(queues)}",
        ]

        if concurrency:
            worker_args.append(f"--concurrency={concurrency}")

        if hostname:
            worker_args.append(f"--hostname={hostname}")

        if beat:
            worker_args.append("--beat")

        print_success("Worker starting...")
        print_info("Press Ctrl+C to stop")
        print_info("")

        # Start the worker using Celery's programmatic API
        app.worker_main(argv=worker_args)

    except ImportError as e:
        print_error(f"Failed to import Celery: {e}")
        print_error("Make sure Celery is installed: pip install celery[redis]")
        raise click.Abort()

    except KeyboardInterrupt:
        print_info("\nWorker stopped")

    except Exception as e:
        print_error(f"Worker failed: {e}")
        if ctx.obj.get("verbose"):
            raise
        raise click.Abort()


@worker.command(name="status")
@click.pass_context
def worker_status(ctx: click.Context) -> None:
    """
    Show status of active Celery workers.

    Examples:

        pyworkflow worker status
    """
    config = ctx.obj.get("config", {})
    output = ctx.obj.get("output", "table")

    # Get broker config
    celery_config = config.get("celery", {})
    broker_url = celery_config.get(
        "broker",
        os.getenv("PYWORKFLOW_CELERY_BROKER", "redis://localhost:6379/0"),
    )

    try:
        from pyworkflow.celery.app import create_celery_app

        app = create_celery_app(broker_url=broker_url)

        # Get active workers
        inspect = app.control.inspect()
        active = inspect.active()
        stats = inspect.stats()
        ping = inspect.ping()

        if not ping:
            print_warning("No active workers found")
            print_info(f"\nStart a worker with: pyworkflow worker run")
            return

        workers = []
        for worker_name, worker_stats in (stats or {}).items():
            worker_info = {
                "name": worker_name,
                "status": "online" if worker_name in (ping or {}) else "offline",
                "concurrency": worker_stats.get("pool", {}).get("max-concurrency", "N/A"),
                "processed": worker_stats.get("total", {}).get("pyworkflow.start_workflow", 0)
                + worker_stats.get("total", {}).get("pyworkflow.execute_step", 0)
                + worker_stats.get("total", {}).get("pyworkflow.resume_workflow", 0),
            }

            # Get active tasks count
            if active and worker_name in active:
                worker_info["active_tasks"] = len(active[worker_name])
            else:
                worker_info["active_tasks"] = 0

            workers.append(worker_info)

        if output == "json":
            format_json(workers)
        elif output == "plain":
            for w in workers:
                print(f"{w['name']}: {w['status']}")
        else:
            table_data = [
                {
                    "Worker": w["name"],
                    "Status": w["status"],
                    "Concurrency": str(w["concurrency"]),
                    "Active Tasks": str(w["active_tasks"]),
                    "Processed": str(w["processed"]),
                }
                for w in workers
            ]
            format_table(
                table_data,
                ["Worker", "Status", "Concurrency", "Active Tasks", "Processed"],
                title="Celery Workers",
            )

    except ImportError as e:
        print_error(f"Failed to import Celery: {e}")
        raise click.Abort()

    except Exception as e:
        print_error(f"Failed to get worker status: {e}")
        print_info("Make sure the broker is running and accessible")
        if ctx.obj.get("verbose"):
            raise
        raise click.Abort()


@worker.command(name="list")
@click.pass_context
def list_workers(ctx: click.Context) -> None:
    """
    List all registered Celery workers.

    Examples:

        pyworkflow worker list
    """
    # This is an alias for status with simplified output
    ctx.invoke(worker_status)


@worker.command(name="queues")
@click.pass_context
def list_queues(ctx: click.Context) -> None:
    """
    Show available task queues and their configuration.

    Examples:

        pyworkflow worker queues
    """
    output = ctx.obj.get("output", "table")

    queues = [
        {
            "name": "pyworkflow.default",
            "purpose": "General tasks",
            "routing_key": "workflow.#",
        },
        {
            "name": "pyworkflow.workflows",
            "purpose": "Workflow orchestration",
            "routing_key": "workflow.workflow.#",
        },
        {
            "name": "pyworkflow.steps",
            "purpose": "Step execution (heavy work)",
            "routing_key": "workflow.step.#",
        },
        {
            "name": "pyworkflow.schedules",
            "purpose": "Sleep resumption scheduling",
            "routing_key": "workflow.schedule.#",
        },
    ]

    if output == "json":
        format_json(queues)
    elif output == "plain":
        for q in queues:
            print(q["name"])
    else:
        table_data = [
            {
                "Queue": q["name"],
                "Purpose": q["purpose"],
                "Routing Key": q["routing_key"],
            }
            for q in queues
        ]
        format_table(
            table_data,
            ["Queue", "Purpose", "Routing Key"],
            title="Task Queues",
        )

    print_info("\nUsage:")
    print_info("  pyworkflow worker run --workflow   # Process workflow queue only")
    print_info("  pyworkflow worker run --step       # Process step queue only")
    print_info("  pyworkflow worker run --schedule   # Process schedule queue only")
