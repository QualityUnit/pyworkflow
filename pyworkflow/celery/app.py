"""
Celery application for distributed workflow execution.

This module configures Celery for:
- Distributed step execution across workers
- Automatic retry with exponential backoff
- Scheduled task execution (sleep resumption)
- Result persistence

Note: With Python 3.13, you may see "BufferError: Existing exports of data"
warnings in Celery logs. This is a known compatibility issue between Python 3.13's
garbage collector and Celery's saferepr module. It does not affect functionality.
"""

import os
from typing import Any
from urllib.parse import urlparse

from celery import Celery
from celery.signals import worker_init, worker_process_init, worker_shutdown
from kombu import Exchange, Queue

from pyworkflow.observability.logging import configure_logging

# Track if logging has been configured in this process
_logging_configured = False


def _configure_worker_logging() -> None:
    """Configure logging for the current worker process."""
    global _logging_configured
    if not _logging_configured:
        from loguru import logger as loguru_logger

        # Enable pyworkflow logging (may have been disabled by CLI)
        loguru_logger.enable("pyworkflow")

        log_level = os.getenv("PYWORKFLOW_LOG_LEVEL", "INFO").upper()
        configure_logging(level=log_level)
        _logging_configured = True


def is_sentinel_url(url: str) -> bool:
    """Check if URL uses sentinel:// or sentinel+ssl:// protocol."""
    return url.startswith("sentinel://") or url.startswith("sentinel+ssl://")


def parse_sentinel_url(url: str) -> tuple[list[tuple[str, int]], int, str | None]:
    """
    Parse a sentinel:// URL into sentinel hosts, database number, and password.

    Format: sentinel://[password@]host1:port1,host2:port2/db_number

    Args:
        url: Sentinel URL (sentinel:// or sentinel+ssl://)

    Returns:
        Tuple of ([(host, port), ...], db_number, password or None)

    Examples:
        >>> parse_sentinel_url("sentinel://host1:26379,host2:26379/0")
        ([('host1', 26379), ('host2', 26379)], 0, None)

        >>> parse_sentinel_url("sentinel://mypassword@host1:26379/0")
        ([('host1', 26379)], 0, 'mypassword')
    """
    # Remove protocol prefix
    if url.startswith("sentinel+ssl://"):
        url_without_protocol = url[len("sentinel+ssl://") :]
    elif url.startswith("sentinel://"):
        url_without_protocol = url[len("sentinel://") :]
    else:
        raise ValueError(f"Invalid sentinel URL: {url}")

    # Extract password if present (password@hosts)
    password: str | None = None
    if "@" in url_without_protocol:
        password, url_without_protocol = url_without_protocol.split("@", 1)

    # Extract database number from path
    db_number = 0
    if "/" in url_without_protocol:
        hosts_part, db_part = url_without_protocol.rsplit("/", 1)
        # Handle query params in db part
        if "?" in db_part:
            db_part = db_part.split("?")[0]
        if db_part:
            db_number = int(db_part)
    else:
        hosts_part = url_without_protocol
        # Handle query params
        if "?" in hosts_part:
            hosts_part = hosts_part.split("?")[0]

    # Parse hosts
    sentinels: list[tuple[str, int]] = []
    for host_port in hosts_part.split(","):
        host_port = host_port.strip()
        if not host_port:
            continue
        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
            sentinels.append((host, int(port_str)))
        else:
            # Default Sentinel port
            sentinels.append((host_port, 26379))

    return sentinels, db_number, password


def discover_workflows(modules: list[str] | None = None) -> None:
    """
    Discover and import workflow modules to register workflows with Celery workers.

    This function imports Python modules containing workflow definitions so that
    Celery workers can find and execute them.

    Args:
        modules: List of module paths to import (e.g., ["myapp.workflows", "myapp.tasks"])
                If None, reads from PYWORKFLOW_DISCOVER environment variable

    Environment Variables:
        PYWORKFLOW_DISCOVER: Comma-separated list of modules to import
                            Example: "myapp.workflows,myapp.tasks,examples.functional.basic_workflow"

    Examples:
        # Discover from environment variable
        discover_workflows()

        # Discover specific modules
        discover_workflows(["myapp.workflows", "myapp.tasks"])
    """
    if modules is None:
        # Read from environment variable
        discover_env = os.getenv("PYWORKFLOW_DISCOVER", "")
        if not discover_env:
            return
        modules = [m.strip() for m in discover_env.split(",") if m.strip()]

    for module_path in modules:
        try:
            __import__(module_path)
            print(f"✓ Discovered workflows from: {module_path}")
        except ImportError as e:
            print(f"✗ Failed to import {module_path}: {e}")


def create_celery_app(
    broker_url: str | None = None,
    result_backend: str | None = None,
    app_name: str = "pyworkflow",
    sentinel_master_name: str | None = None,
    broker_transport_options: dict[str, Any] | None = None,
    result_backend_transport_options: dict[str, Any] | None = None,
) -> Celery:
    """
    Create and configure a Celery application for PyWorkflow.

    Args:
        broker_url: Celery broker URL. Priority: parameter > PYWORKFLOW_CELERY_BROKER env var > redis://localhost:6379/0
        result_backend: Result backend URL. Priority: parameter > PYWORKFLOW_CELERY_RESULT_BACKEND env var > redis://localhost:6379/1
        app_name: Application name
        sentinel_master_name: Redis Sentinel master name. Priority: parameter > PYWORKFLOW_CELERY_SENTINEL_MASTER env var > "mymaster"
        broker_transport_options: Additional transport options for the broker (merged with defaults)
        result_backend_transport_options: Additional transport options for the result backend (merged with defaults)

    Returns:
        Configured Celery application

    Environment Variables:
        PYWORKFLOW_CELERY_BROKER: Celery broker URL (used if broker_url param not provided)
        PYWORKFLOW_CELERY_RESULT_BACKEND: Result backend URL (used if result_backend param not provided)
        PYWORKFLOW_CELERY_SENTINEL_MASTER: Sentinel master name (used if sentinel_master_name param not provided)

    Examples:
        # Default configuration (uses env vars if set, otherwise localhost Redis)
        app = create_celery_app()

        # Custom Redis
        app = create_celery_app(
            broker_url="redis://redis-host:6379/0",
            result_backend="redis://redis-host:6379/1"
        )

        # RabbitMQ with Redis backend
        app = create_celery_app(
            broker_url="amqp://guest:guest@rabbitmq:5672//",
            result_backend="redis://localhost:6379/1"
        )

        # Redis Sentinel for high availability
        app = create_celery_app(
            broker_url="sentinel://sentinel1:26379,sentinel2:26379,sentinel3:26379/0",
            result_backend="sentinel://sentinel1:26379,sentinel2:26379,sentinel3:26379/1",
            sentinel_master_name="mymaster"
        )
    """
    # Priority: parameter > environment variable > hardcoded default
    broker_url = broker_url or os.getenv("PYWORKFLOW_CELERY_BROKER") or "redis://localhost:6379/0"
    result_backend = (
        result_backend
        or os.getenv("PYWORKFLOW_CELERY_RESULT_BACKEND")
        or "redis://localhost:6379/1"
    )

    # Detect broker and backend types
    is_sentinel_broker = is_sentinel_url(broker_url)
    is_sentinel_backend = is_sentinel_url(result_backend)
    is_redis_broker = broker_url.startswith("redis://") or broker_url.startswith("rediss://")
    is_redis_backend = result_backend.startswith("redis://") or result_backend.startswith(
        "rediss://"
    )

    # Get Sentinel master name from param, env, or default
    master_name = (
        sentinel_master_name
        or os.getenv("PYWORKFLOW_CELERY_SENTINEL_MASTER")
        or "mymaster"
    )

    # Build transport options for broker
    if is_sentinel_broker:
        sentinel_broker_opts: dict[str, Any] = {"master_name": master_name}
        # Merge with user options (user takes precedence)
        final_broker_opts: dict[str, Any] = {
            "visibility_timeout": 3600,
            **sentinel_broker_opts,
            **(broker_transport_options or {}),
        }
    else:
        final_broker_opts = {
            "visibility_timeout": 3600,
            **(broker_transport_options or {}),
        }

    # Build transport options for result backend
    if is_sentinel_backend:
        sentinel_backend_opts: dict[str, Any] = {"master_name": master_name}
        final_backend_opts: dict[str, Any] = {
            "visibility_timeout": 3600,
            **sentinel_backend_opts,
            **(result_backend_transport_options or {}),
        }
    else:
        final_backend_opts = {
            "visibility_timeout": 3600,
            **(result_backend_transport_options or {}),
        }

    app = Celery(
        app_name,
        broker=broker_url,
        backend=result_backend,
        include=[
            "pyworkflow.celery.tasks",
        ],
    )

    # Configure Celery
    app.conf.update(
        # Task execution settings
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # Broker transport options - prevent task redelivery
        # See: https://github.com/celery/celery/issues/5935
        broker_transport_options=final_broker_opts,
        result_backend_transport_options=final_backend_opts,
        # Task routing
        task_default_queue="pyworkflow.default",
        task_default_exchange="pyworkflow",
        task_default_exchange_type="topic",
        task_default_routing_key="workflow.default",
        # Task queues
        task_queues=(
            Queue(
                "pyworkflow.default",
                Exchange("pyworkflow", type="topic"),
                routing_key="workflow.#",
            ),
            Queue(
                "pyworkflow.steps",
                Exchange("pyworkflow", type="topic"),
                routing_key="workflow.step.#",
            ),
            Queue(
                "pyworkflow.workflows",
                Exchange("pyworkflow", type="topic"),
                routing_key="workflow.workflow.#",
            ),
            Queue(
                "pyworkflow.schedules",
                Exchange("pyworkflow", type="topic"),
                routing_key="workflow.schedule.#",
            ),
        ),
        # Result backend settings
        result_expires=3600,  # 1 hour
        result_persistent=True,
        # Task execution
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,  # Fair task distribution
        # Retry settings
        task_autoretry_for=(),
        task_retry_backoff=True,
        task_retry_backoff_max=600,  # 10 minutes max
        task_retry_jitter=True,
        # Monitoring
        worker_send_task_events=True,
        task_send_sent_event=True,
        # Beat scheduler (for sleep resumption)
        beat_schedule={},
        # Logging
        worker_log_format="[%(asctime)s: %(levelname)s/%(processName)s] %(message)s",
        worker_task_log_format="[%(asctime)s: %(levelname)s/%(processName)s] [%(task_name)s(%(task_id)s)] %(message)s",
    )

    # Configure singleton locking for Redis or Sentinel brokers
    # This enables distributed locking to prevent duplicate task execution
    if is_redis_broker or is_sentinel_broker:
        app.conf.update(
            singleton_backend_url=broker_url,
            singleton_backend_is_sentinel=is_sentinel_broker,
            singleton_sentinel_master=master_name if is_sentinel_broker else None,
            singleton_key_prefix="pyworkflow:lock:",
            singleton_lock_expiry=3600,  # 1 hour TTL (safety net)
        )

    # Note: Logging is configured via Celery signals (worker_init, worker_process_init)
    # to ensure proper initialization AFTER process forking.
    # See on_worker_init() and on_worker_process_init() below.

    # Auto-discover workflows from environment variable or configured modules
    discover_workflows()

    return app


# Global Celery app instance
# Can be customized by calling create_celery_app() with custom config
celery_app = create_celery_app()


# ========== Celery Worker Signals ==========
# These signals ensure proper initialization in forked worker processes


@worker_init.connect
def on_worker_init(**kwargs):
    """
    Called when the main worker process starts (before forking).

    For prefork pool, this runs in the parent process.
    For solo/threads pool, this is the main initialization point.
    """
    _configure_worker_logging()


@worker_process_init.connect
def on_worker_process_init(**kwargs):
    """
    Called when a worker child process is initialized (after forking).

    This is critical for prefork pool:
    - loguru's background thread doesn't survive fork()
    - We need a persistent event loop for connection pool reuse
    """
    _configure_worker_logging()

    # Initialize persistent event loop for this worker
    from pyworkflow.celery.loop import init_worker_loop

    init_worker_loop()


@worker_shutdown.connect
def on_worker_shutdown(**kwargs):
    """
    Called when the worker is shutting down.

    Cleans up:
    - Storage backend connections (PostgreSQL connection pools, etc.)
    - The persistent event loop
    """
    from loguru import logger

    from pyworkflow.celery.loop import close_worker_loop, run_async
    from pyworkflow.storage.config import disconnect_all_cached

    try:
        # Clean up storage connections using the persistent loop
        run_async(disconnect_all_cached())
    except Exception as e:
        # Log but don't fail shutdown
        logger.warning(f"Error during storage cleanup on shutdown: {e}")
    finally:
        # Close the persistent event loop
        close_worker_loop()


def get_celery_app() -> Celery:
    """
    Get the global Celery application instance.

    Returns:
        Celery application

    Example:
        from pyworkflow.celery.app import get_celery_app

        app = get_celery_app()
        app.conf.update(broker_url="redis://custom:6379/0")
    """
    return celery_app
