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

# Post-return lifecycle state requested by terminate() / suspend() helpers.
# The dispatcher reads this after the step lifecycle function returns to
# decide whether to write "waiting", "suspended", or "terminated".
_post_return_state: ContextVar[dict | None] = ContextVar("_post_return_state", default=None)


async def terminate() -> None:
    """
    Mark the current stream step as permanently terminated.

    The dispatcher will set the subscription status to ``terminated`` after
    the lifecycle function returns, and will not invoke this step again.
    """
    state = _post_return_state.get() or {}
    state = dict(state)
    state["status"] = "terminated"
    _post_return_state.set(state)


async def set_result(value: Any) -> None:
    """Attach a result payload to the current stream step.

    The dispatcher persists this payload to the subscription row after the
    lifecycle function returns. ``run_stream_workflow`` exposes it on
    ``StreamWorkflowResult.step_results`` so the parent ``@workflow`` can
    read step output without going through a checkpoint.

    Replaces ``save_checkpoint`` for the "communicate completion to parent"
    use case. Plain ``dict``-shaped values serialize via the storage
    backend's JSON column.
    """
    state = _post_return_state.get() or {}
    state = dict(state)
    state["result"] = value
    _post_return_state.set(state)


async def suspend(
    reason: str,
    resume_signals: list[str] | None = None,
) -> None:
    """
    Mark the current stream step as suspended.

    The dispatcher will set the subscription status to ``suspended`` after
    the lifecycle function returns. The stream workflow runtime aggregates
    suspended steps and propagates a ``SuspensionSignal`` to the parent
    ``@workflow``.

    Args:
        reason: Human-readable reason; also used as the SuspensionSignal
            reason tag (e.g. ``"hitl:<hitl_id>"``).
        resume_signals: Optional whitelist of signal types that may flip
            the step back to ``waiting``. Defaults to the step's existing
            ``signals=`` map.
    """
    state = _post_return_state.get() or {}
    state = dict(state)
    state.update(
        {
            "status": "suspended",
            "reason": reason,
            "resume_signals": list(resume_signals) if resume_signals else None,
        }
    )
    _post_return_state.set(state)


def consume_post_return_state() -> dict | None:
    """Read and clear the pending post-return state for the current context."""
    state = _post_return_state.get()
    if state is not None:
        _post_return_state.set(None)
    return state


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


async def poll_inbox(
    signal_types: list[str] | None = None,
) -> list[Signal]:
    """Get unacknowledged signals for the current running stream step.

    Allows a step that is in ``running`` status to discover signals that
    arrived while it was executing.  Uses the same storage query as the
    post-execution drain mechanism (``get_pending_signals``) but can be
    called from *within* the lifecycle function, so a long-running step
    does not have to return first.

    Signals are filtered to the current ``stream_run_id`` to prevent
    cross-run leakage.

    Args:
        signal_types: Optional whitelist.  When provided, only signals
            whose ``signal_type`` is in this list are returned.

    Returns:
        A list of :class:`Signal` objects ordered by sequence number.
    """
    from loguru import logger

    storage = _current_storage.get()
    stream_id = _current_stream_id.get()
    step_run_id = _current_step_run_id.get()
    stream_run_id = _current_stream_run_id.get()

    if not storage or not stream_id or not step_run_id:
        return []

    try:
        pending = await storage.get_pending_signals(stream_id, step_run_id)
    except Exception:
        logger.debug("[poll_inbox] get_pending_signals failed", exc_info=True)
        return []

    results: list[Signal] = []
    for row in pending:
        # Filter to current stream run
        if stream_run_id and row.get("stream_run_id") != stream_run_id:
            continue
        # Optional signal type filter
        if signal_types and row.get("signal_type") not in signal_types:
            continue
        results.append(
            Signal(
                signal_id=row["signal_id"],
                stream_id=row["stream_id"],
                signal_type=row["signal_type"],
                payload=row.get("payload") or {},
                sequence=row.get("sequence", 0),
                source_run_id=row.get("source_run_id"),
                stream_run_id=row.get("stream_run_id"),
                metadata=row.get("metadata") or {},
            )
        )
    return results


async def acknowledge_inbox_signal(signal_id: str) -> None:
    """Acknowledge a signal retrieved via :func:`poll_inbox`.

    Once acknowledged the signal will not appear in subsequent
    ``poll_inbox`` calls or in the post-execution drain, preventing
    double processing.
    """
    storage = _current_storage.get()
    step_run_id = _current_step_run_id.get()
    if storage and step_run_id:
        await storage.acknowledge_signal(signal_id, step_run_id)
