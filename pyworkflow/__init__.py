"""
PyWorkflow - Durable, event-sourced workflows for Python

A Python implementation of workflow orchestration inspired by Vercel Workflow,
providing fault-tolerant, long-running workflows with automatic retry, sleep/delay,
and webhook integration.

Quick Start:
    >>> from pyworkflow import workflow, step, start
    >>>
    >>> @workflow
    >>> async def my_workflow(name: str):
    >>>     result = await process_step(name)
    >>>     return result
    >>>
    >>> @step
    >>> async def process_step(name: str):
    >>>     return f"Hello, {name}!"
    >>>
    >>> # Execute workflow
    >>> run_id = await start(my_workflow, "Alice")
"""

__version__ = "0.1.0"

# Core decorators and primitives
from pyworkflow.core.step import step
from pyworkflow.core.workflow import workflow
from pyworkflow.primitives.sleep import sleep

# Execution engine
from pyworkflow.engine.executor import (
    get_workflow_events,
    get_workflow_run,
    resume,
    start,
)

# Exceptions
from pyworkflow.core.exceptions import (
    FatalError,
    RetryableError,
    SuspensionSignal,
    WorkflowAlreadyRunningError,
    WorkflowError,
    WorkflowNotFoundError,
)

# Context access
from pyworkflow.core.context import get_current_context, has_current_context

# Storage backends
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun

# Logging and observability
from pyworkflow.observability.logging import (
    bind_step_context,
    bind_workflow_context,
    configure_logging,
    get_logger,
)

__all__ = [
    # Version
    "__version__",
    # Core decorators
    "workflow",
    "step",
    # Primitives
    "sleep",
    # Execution
    "start",
    "resume",
    "get_workflow_run",
    "get_workflow_events",
    # Exceptions
    "WorkflowError",
    "FatalError",
    "RetryableError",
    "SuspensionSignal",
    "WorkflowNotFoundError",
    "WorkflowAlreadyRunningError",
    # Context
    "get_current_context",
    "has_current_context",
    # Storage
    "StorageBackend",
    "FileStorageBackend",
    "WorkflowRun",
    "RunStatus",
    # Logging
    "configure_logging",
    "get_logger",
    "bind_workflow_context",
    "bind_step_context",
]
