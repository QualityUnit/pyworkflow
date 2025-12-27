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

from celery import Celery
from kombu import Exchange, Queue

from pyworkflow.observability.logging import configure_logging


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
) -> Celery:
    """
    Create and configure a Celery application for PyWorkflow.

    Args:
        broker_url: Celery broker URL. Priority: parameter > PYWORKFLOW_CELERY_BROKER env var > redis://localhost:6379/0
        result_backend: Result backend URL. Priority: parameter > PYWORKFLOW_CELERY_RESULT_BACKEND env var > redis://localhost:6379/1
        app_name: Application name

    Returns:
        Configured Celery application

    Environment Variables:
        PYWORKFLOW_CELERY_BROKER: Celery broker URL (used if broker_url param not provided)
        PYWORKFLOW_CELERY_RESULT_BACKEND: Result backend URL (used if result_backend param not provided)

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
    """
    # Priority: parameter > environment variable > hardcoded default
    broker_url = broker_url or os.getenv("PYWORKFLOW_CELERY_BROKER") or "redis://localhost:6379/0"
    result_backend = (
        result_backend
        or os.getenv("PYWORKFLOW_CELERY_RESULT_BACKEND")
        or "redis://localhost:6379/1"
    )

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
        task_autoretry_for=(Exception,),
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

    # Configure logging
    configure_logging(level="INFO")

    # Auto-discover workflows from environment variable or configured modules
    discover_workflows()

    return app


# Global Celery app instance
# Can be customized by calling create_celery_app() with custom config
celery_app = create_celery_app()


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
