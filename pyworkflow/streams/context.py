"""
Stream step context primitives.

Provides get_current_signal(), get_checkpoint(), and save_checkpoint()
for use within stream step lifecycle functions.
"""

from contextvars import ContextVar
from typing import Any

from pyworkflow.streams.checkpoint import get_checkpoint_backend
from pyworkflow.streams.signal import Signal

# Context variables for stream step execution
_current_signal: ContextVar[Signal | None] = ContextVar("_current_signal", default=None)
_current_step_run_id: ContextVar[str | None] = ContextVar("_current_step_run_id", default=None)
_current_stream_id: ContextVar[str | None] = ContextVar("_current_stream_id", default=None)
_current_storage: ContextVar[Any] = ContextVar("_current_storage", default=None)
_current_stream_run_id: ContextVar[str | None] = ContextVar("_current_stream_run_id", default=None)


def set_stream_step_context(
    step_run_id: str,
    stream_id: str,
    signal: Signal | None = None,
    storage: Any = None,
    stream_run_id: str | None = None,
) -> tuple:
    """
    Set the stream step context variables.

    Returns tokens for resetting.
    """
    t1 = _current_signal.set(signal)
    t2 = _current_step_run_id.set(step_run_id)
    t3 = _current_stream_id.set(stream_id)
    t4 = _current_storage.set(storage)
    t5 = _current_stream_run_id.set(stream_run_id)
    return (t1, t2, t3, t4, t5)


def reset_stream_step_context(tokens: tuple) -> None:
    """Reset the stream step context variables."""
    t1, t2, t3, t4, t5 = tokens
    _current_signal.reset(t1)
    _current_step_run_id.reset(t2)
    _current_stream_id.reset(t3)
    _current_storage.reset(t4)
    _current_stream_run_id.reset(t5)


async def get_current_signal() -> Signal | None:
    """
    Get the signal that triggered the current lifecycle resume.

    Returns None on first start (initialization phase).
    Returns the Signal that caused ctx.resume() on subsequent runs.
    """
    return _current_signal.get()


async def get_checkpoint() -> dict | None:
    """
    Load saved checkpoint data for the current stream step.

    Returns None if no checkpoint has been saved yet.
    """
    step_run_id = _current_step_run_id.get()
    if step_run_id is None:
        raise RuntimeError(
            "get_checkpoint() must be called within a stream step lifecycle function."
        )
    storage = _current_storage.get()
    backend = get_checkpoint_backend(storage=storage)
    return await backend.load(step_run_id)


async def save_checkpoint(data: dict) -> None:
    """
    Save checkpoint data for the current stream step.

    This data will be available via get_checkpoint() after the step
    is resumed.

    Args:
        data: Dictionary of checkpoint data to persist
    """
    step_run_id = _current_step_run_id.get()
    if step_run_id is None:
        raise RuntimeError(
            "save_checkpoint() must be called within a stream step lifecycle function."
        )
    storage = _current_storage.get()
    backend = get_checkpoint_backend(storage=storage)
    await backend.save(step_run_id, data)


def get_stream_run_id() -> str | None:
    """Get the current stream run ID from context."""
    return _current_stream_run_id.get()


def set_stream_run_id(stream_run_id: str | None) -> Any:
    """
    Set the stream run ID in context.

    Returns a token that can be used to reset the value.
    """
    return _current_stream_run_id.set(stream_run_id)
