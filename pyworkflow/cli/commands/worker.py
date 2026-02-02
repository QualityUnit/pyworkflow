"""Worker management commands for Celery runtime."""

import os

import click

from pyworkflow.cli.output.formatters import (
    format_json,
    format_table,
    print_error,
    print_info,
    print_success,
    print_warning,
)


@click.group(name="worker")
def worker() -> None:
    """Manage Celery workers for workflow execution."""
    pass


@worker.command(
    name="run",
    context_settings={
        "allow_extra_args": True,
        "allow_interspersed_args": False,
    },
)
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
@click.option(
    "--pool",
    type=click.Choice(["prefork", "solo", "eventlet", "gevent"], case_sensitive=False),
    default="prefork",
    help="Worker pool type (default: prefork). Use 'solo' for debugging with breakpoints",
)
@click.option(
    "--sentinel-master",
    default=None,
    help="Redis Sentinel master name (required for sentinel:// URLs)",
)
@click.option(
    "--autoscale",
    default=None,
    help="Enable autoscaling: MIN,MAX (e.g., '2,10')",
)
@click.option(
    "--max-tasks-per-child",
    type=int,
    default=None,
    help="Maximum tasks per worker child before replacement",
)
@click.option(
    "--prefetch-multiplier",
    type=int,
    default=None,
    help="Task prefetch count per worker process",
)
@click.option(
    "--time-limit",
    type=float,
    default=None,
    help="Hard time limit for tasks in seconds",
)
@click.option(
    "--soft-time-limit",
    type=float,
    default=None,
    help="Soft time limit for tasks in seconds",
)
@click.pass_context
def run_worker(
    ctx: click.Context,
    queue_workflow: bool,
    queue_step: bool,
    queue_schedule: bool,
    loglevel: str,
    hostname: str | None,
    beat: bool,
    pool: str | None,
    sentinel_master: str | None,
    autoscale: str | None,
    max_tasks_per_child: int | None,
    prefetch_multiplier: int | None,
    time_limit: float | None,
    soft_time_limit: float | None,
) -> None:
    """
    Start a Celery worker for processing workflows.

    By default, processes all queues. Use --workflow, --step, or --schedule
    flags to limit to specific queue types.

    Use -- to pass arbitrary Celery arguments directly to the worker.

    Examples:

        # Start a worker processing all queues
        pyworkflow worker run

        # Start a workflow orchestration worker only
        pyworkflow worker run --workflow

        # Start a schedule worker (for sleep resumption)
        pyworkflow worker run --schedule

        # Start with beat scheduler
        pyworkflow worker run --beat

        # Start with custom log level
        pyworkflow worker run --loglevel debug

        # Enable autoscaling (min 2, max 10 workers)
        pyworkflow worker run --step --autoscale 2,10

        # Set task limits
        pyworkflow worker run --max-tasks-per-child 100 --time-limit 300

        # Pass arbitrary Celery arguments after --
        pyworkflow worker run -- --max-memory-per-child=200000
    """
    # Get config from CLI context (TOML config)
    config = ctx.obj.get("config", {})
    module = ctx.obj.get("module")

    # Also try to load YAML config if it exists
    from pyworkflow.cli.utils.discovery import _load_yaml_config

    yaml_config = _load_yaml_config()
    if yaml_config:
        # Merge YAML config (lower priority) with TOML config (higher priority)
        merged_config = {**yaml_config, **config}
        # For nested dicts like 'celery', merge them too
        if "celery" in yaml_config and "celery" not in config:
            merged_config["celery"] = yaml_config["celery"]
        config = merged_config

    # Get extra args passed after --
    extra_args = ctx.args

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

    # Worker processes always need logging enabled
    from loguru import logger as loguru_logger

    loguru_logger.enable("pyworkflow")

    # Get Sentinel master from CLI option, config file, or environment
    sentinel_master_name = sentinel_master or celery_config.get(
        "sentinel_master",
        os.getenv("PYWORKFLOW_CELERY_SENTINEL_MASTER"),
    )

    print_info("Starting Celery worker...")
    print_info(f"Broker: {broker_url}")
    if broker_url.startswith("sentinel://") or broker_url.startswith("sentinel+ssl://"):
        print_info(f"Sentinel master: {sentinel_master_name or 'mymaster'}")
    print_info(f"Queues: {', '.join(queues)}")
    if autoscale:
        print_info(f"Autoscale: {autoscale} (min,max)")
    print_info(f"Pool: {pool}")
    if extra_args:
        print_info(f"Extra args: {' '.join(extra_args)}")

    try:
        # Discover workflows using CLI discovery (reads from --module, env var, or YAML config)
        from pyworkflow.cli.utils.discovery import discover_workflows

        discover_workflows(module, config)

        # Import and configure Celery app (after discovery so workflows are registered)
        from pyworkflow.celery.app import create_celery_app

        # Create or get Celery app with configured broker
        app = create_celery_app(
            broker_url=broker_url,
            result_backend=result_backend,
            sentinel_master_name=sentinel_master_name,
        )

        # Log discovered workflows and steps
        from pyworkflow import list_steps, list_workflows

        workflows = list_workflows()
        steps = list_steps()

        if workflows:
            print_info(f"Registered {len(workflows)} workflow(s):")
            for name in sorted(workflows.keys()):
                print_info(f"  - {name}")
        else:
            print_warning("No workflows registered!")
            print_warning("Specify workflows using one of:")
            print_warning("  1. --module flag: pyworkflow --module myapp.workflows worker run")
            print_warning(
                "  2. Environment: PYWORKFLOW_DISCOVER=myapp.workflows pyworkflow worker run"
            )
            print_warning(
                "  3. Config file: Create pyworkflow.config.yaml with 'module: myapp.workflows'"
            )
            print_info("")

        if steps:
            print_info(f"Registered {len(steps)} step(s):")
            for name in sorted(steps.keys()):
                print_info(f"  - {name}")

        print_info("")

        # Configure worker arguments
        worker_args = [
            "worker",
            f"--loglevel={loglevel.upper()}",
            f"--pool={pool}",  # Always set (default: prefork)
        ]

        worker_args.append(f"--queues={','.join(queues)}")

        if hostname:
            worker_args.append(f"--hostname={hostname}")

        if beat:
            worker_args.append("--beat")
            worker_args.append("--scheduler=pyworkflow.celery.scheduler:PyWorkflowScheduler")

        # Add new explicit options
        if autoscale:
            worker_args.append(f"--autoscale={autoscale}")

        if max_tasks_per_child is not None:
            worker_args.append(f"--max-tasks-per-child={max_tasks_per_child}")

        if prefetch_multiplier is not None:
            worker_args.append(f"--prefetch-multiplier={prefetch_multiplier}")

        if time_limit is not None:
            worker_args.append(f"--time-limit={time_limit}")

        if soft_time_limit is not None:
            worker_args.append(f"--soft-time-limit={soft_time_limit}")

        # Append extra args last (highest priority - they can override anything)
        if extra_args:
            worker_args.extend(extra_args)

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
            print_info("\nStart a worker with: pyworkflow worker run")
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
