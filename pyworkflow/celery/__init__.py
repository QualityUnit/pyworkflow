"""
Celery integration for distributed workflow execution.

This module provides Celery-based distributed execution for PyWorkflow,
enabling horizontal scaling across multiple workers.

Usage:
    # Start Celery worker
    celery -A pyworkflow.celery.app worker --loglevel=info

    # Start Celery beat (for scheduled tasks)
    celery -A pyworkflow.celery.app beat --loglevel=info

    # Use in code
    from pyworkflow.celery import celery_app, start_workflow_task

    # Start workflow in distributed mode
    result = start_workflow_task.delay("my_workflow", args_json, kwargs_json)
"""

from pyworkflow.celery.app import celery_app, create_celery_app, get_celery_app
from pyworkflow.celery.scheduler import PyWorkflowScheduler
from pyworkflow.celery.tasks import (
    execute_scheduled_workflow_task,
    execute_step_task,
    resume_workflow_task,
    schedule_workflow_resumption,
    start_workflow_task,
)

__all__ = [
    "celery_app",
    "create_celery_app",
    "get_celery_app",
    "execute_step_task",
    "start_workflow_task",
    "resume_workflow_task",
    "schedule_workflow_resumption",
    "execute_scheduled_workflow_task",
    "PyWorkflowScheduler",
]
