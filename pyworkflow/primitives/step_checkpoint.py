"""
Checkpoint primitives for use within @step functions.

Allows steps to persist state across suspend/resume cycles (e.g., when
using step_hook() for human-in-the-loop patterns).

Usage:
    @step
    async def my_agent_step():
        checkpoint = await load_step_checkpoint()
        if checkpoint:
            state = checkpoint["state"]
        else:
            state = await init_agent()
            await save_step_checkpoint({"state": state})

        result = await step_hook("human_review")
        return await process(state, result)
"""

from contextvars import ContextVar
from typing import Any

from loguru import logger

# Step execution context for checkpoint operations
_step_run_id: ContextVar[str | None] = ContextVar("_step_run_id", default=None)
_step_storage: ContextVar[Any] = ContextVar("_step_storage", default=None)


def set_step_execution_context(
    step_run_id: str,
    storage: Any,
) -> tuple:
    """
    Set the step execution context for checkpoint and hook operations.

    Called by the step executor before running the step function.

    Args:
        step_run_id: Unique identifier for this step execution (run_id:step_id)
        storage: Storage backend instance

    Returns:
        Tokens for resetting context
    """
    t1 = _step_run_id.set(step_run_id)
    t2 = _step_storage.set(storage)
    return (t1, t2)


def reset_step_execution_context(tokens: tuple) -> None:
    """Reset the step execution context."""
    t1, t2 = tokens
    _step_run_id.reset(t1)
    _step_storage.reset(t2)


def get_step_run_id() -> str | None:
    """Get the current step run ID from context."""
    return _step_run_id.get()


def get_step_storage() -> Any:
    """Get the current storage from step context."""
    return _step_storage.get()


async def save_step_checkpoint(data: dict) -> None:
    """
    Save checkpoint data for the current step.

    Call this before step_hook() to persist state that will survive
    step suspension and resumption.

    Args:
        data: Dictionary of state to persist

    Raises:
        RuntimeError: If called outside a step execution context

    Example:
        @step
        async def my_step():
            state = await compute_something()
            await save_step_checkpoint({"state": state})
            result = await step_hook("approval")
            return await finalize(state, result)
    """
    step_id = _step_run_id.get()
    storage = _step_storage.get()

    if step_id is None or storage is None:
        raise RuntimeError(
            "save_step_checkpoint() must be called within a @step function running in durable mode."
        )

    await storage.save_checkpoint(step_id, data)
    logger.debug(f"Step checkpoint saved for {step_id}")


async def load_step_checkpoint() -> dict | None:
    """
    Load checkpoint data for the current step.

    Returns None if no checkpoint has been saved. Use this at the start
    of your step to restore state after resumption.

    Returns:
        Checkpoint data dict or None

    Raises:
        RuntimeError: If called outside a step execution context

    Example:
        @step
        async def my_step():
            checkpoint = await load_step_checkpoint()
            if checkpoint:
                state = checkpoint["state"]
            else:
                state = await init()
    """
    step_id = _step_run_id.get()
    storage = _step_storage.get()

    if step_id is None or storage is None:
        raise RuntimeError(
            "load_step_checkpoint() must be called within a @step function running in durable mode."
        )

    data = await storage.load_checkpoint(step_id)
    if data is not None:
        logger.debug(f"Step checkpoint loaded for {step_id}")
    return data


async def delete_step_checkpoint() -> None:
    """
    Delete checkpoint data for the current step.

    Call this after the step completes to clean up checkpoint data.

    Raises:
        RuntimeError: If called outside a step execution context
    """
    step_id = _step_run_id.get()
    storage = _step_storage.get()

    if step_id is None or storage is None:
        raise RuntimeError(
            "delete_step_checkpoint() must be called within a @step function "
            "running in durable mode."
        )

    await storage.delete_checkpoint(step_id)
    logger.debug(f"Step checkpoint deleted for {step_id}")
