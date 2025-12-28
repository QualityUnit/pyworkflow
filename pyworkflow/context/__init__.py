"""
Workflow Context - The unified interface for workflow execution.

The context provides implicit access to workflow operations within execution.
Uses Python's contextvars for implicit context passing (similar to Scala's implicits).

Available Contexts:
- LocalContext: In-process execution with optional event sourcing
- AWSContext: AWS Durable Lambda Functions with automatic checkpointing
- MockContext: For testing workflows without side effects

Usage with implicit context:
    from pyworkflow.context import get_context

    async def my_step(order_id: str):
        ctx = get_context()  # Implicitly available
        ctx.log(f"Processing {order_id}")
        return {"order_id": order_id}

    @workflow()
    async def my_workflow(order_id: str):
        # Context is set automatically by @workflow
        ctx = get_context()
        result = await ctx.run(my_step, order_id)
        await ctx.sleep("5m")
        return result

Usage with explicit context (context manager):
    from pyworkflow.context import LocalContext

    async with LocalContext(run_id="run_123", workflow_name="my_workflow") as ctx:
        result = await ctx.run(my_step, "order_123")
"""

from pyworkflow.context.base import (
    WorkflowContext,
    get_context,
    has_context,
    reset_context,
    set_context,
)
from pyworkflow.context.local import LocalContext
from pyworkflow.context.mock import MockContext
from pyworkflow.context.step_context import (
    StepContext,
    get_step_context,
    get_step_context_class,
    has_step_context,
    set_step_context,
)

__all__ = [
    # Base context and helpers
    "WorkflowContext",
    "get_context",
    "has_context",
    "set_context",
    "reset_context",
    # Step context for distributed execution
    "StepContext",
    "get_step_context",
    "has_step_context",
    "set_step_context",
    "get_step_context_class",
    # Context implementations
    "LocalContext",
    "MockContext",
]

# AWS context is optional - only available if aws-durable-execution-sdk installed
try:
    from pyworkflow.context.aws import AWSContext

    __all__.append("AWSContext")
except ImportError:
    pass
