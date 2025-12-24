"""
PyWorkflow - Durable and transient workflows for Python

A Python implementation of workflow orchestration inspired by Vercel Workflow,
providing fault-tolerant, long-running workflows with automatic retry, sleep/delay,
and webhook integration.

Supports both:
- Durable workflows: Event-sourced, persistent, resumable
- Transient workflows: Simple execution without persistence overhead

Quick Start:
    >>> import pyworkflow
    >>> from pyworkflow import workflow, step, start
    >>>
    >>> # Configure defaults
    >>> pyworkflow.configure(default_runtime="local", default_durable=False)
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

# Configuration
from pyworkflow.config import configure, get_config, get_storage, reset_config

# Core decorators and primitives
from pyworkflow.core.step import step
from pyworkflow.core.workflow import workflow
from pyworkflow.primitives.define_hook import TypedHook, define_hook
from pyworkflow.primitives.hooks import hook
from pyworkflow.primitives.resume_hook import ResumeResult, resume_hook
from pyworkflow.primitives.shield import shield
from pyworkflow.primitives.sleep import sleep
from pyworkflow.primitives.child_workflow import start_child_workflow
from pyworkflow.primitives.child_handle import ChildWorkflowHandle

# Execution engine
from pyworkflow.engine.executor import (
    ConfigurationError,
    cancel_workflow,
    get_workflow_events,
    get_workflow_run,
    resume,
    start,
)

# Exceptions
from pyworkflow.core.exceptions import (
    CancellationError,
    ChildWorkflowError,
    ChildWorkflowFailedError,
    FatalError,
    HookAlreadyReceivedError,
    HookExpiredError,
    HookNotFoundError,
    InvalidTokenError,
    MaxNestingDepthError,
    RetryableError,
    SuspensionSignal,
    WorkflowAlreadyRunningError,
    WorkflowError,
    WorkflowNotFoundError,
)

# Context API (new unified context via contextvars)
from pyworkflow.context import (
    WorkflowContext,
    LocalContext,
    MockContext,
    get_context,
    has_context,
    set_context,
    reset_context,
)

# Registry functions
from pyworkflow.core.registry import (
    get_step,
    get_workflow,
    list_steps,
    list_workflows,
)

# Storage backends
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun

# Runtime
from pyworkflow.runtime import Runtime, LocalRuntime, get_runtime, register_runtime

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
    # Configuration
    "configure",
    "get_config",
    "get_storage",
    "reset_config",
    # Core decorators
    "workflow",
    "step",
    # Primitives
    "sleep",
    "hook",
    "define_hook",
    "TypedHook",
    "resume_hook",
    "ResumeResult",
    "shield",
    # Child workflows
    "start_child_workflow",
    "ChildWorkflowHandle",
    # Execution
    "start",
    "resume",
    "cancel_workflow",
    "get_workflow_run",
    "get_workflow_events",
    # Exceptions
    "WorkflowError",
    "FatalError",
    "RetryableError",
    "CancellationError",
    "SuspensionSignal",
    "WorkflowNotFoundError",
    "WorkflowAlreadyRunningError",
    "HookNotFoundError",
    "HookExpiredError",
    "HookAlreadyReceivedError",
    "InvalidTokenError",
    "ConfigurationError",
    "ChildWorkflowError",
    "ChildWorkflowFailedError",
    "MaxNestingDepthError",
    # Context API
    "WorkflowContext",
    "LocalContext",
    "MockContext",
    "get_context",
    "has_context",
    "set_context",
    "reset_context",
    # Registry
    "list_workflows",
    "get_workflow",
    "list_steps",
    "get_step",
    # Storage
    "StorageBackend",
    "FileStorageBackend",
    "InMemoryStorageBackend",
    "WorkflowRun",
    "RunStatus",
    # Runtime
    "Runtime",
    "LocalRuntime",
    "get_runtime",
    "register_runtime",
    # Logging
    "configure_logging",
    "get_logger",
    "bind_workflow_context",
    "bind_step_context",
]
