"""
emit() function for publishing signals to streams.

Signals can be emitted from workflows, steps, or externally.
"""

import uuid
from typing import Any

from loguru import logger
from pydantic import BaseModel

from pyworkflow.streams.signal import Signal


async def emit(
    stream_id: str,
    signal_type: str,
    payload: Any = None,
    *,
    storage: Any = None,
    metadata: dict[str, Any] | None = None,
    stream_run_id: str | None = None,
) -> Signal:
    """
    Publish a signal to a stream.

    Can be called from:
    - Workflow code (auto-detects storage from context)
    - Step code (auto-detects storage from context)
    - External code (requires explicit storage parameter)

    Args:
        stream_id: Target stream identifier
        signal_type: Signal type (e.g., "task.created")
        payload: Signal payload data
        storage: Storage backend (uses configured default if not provided)
        metadata: Optional signal metadata

    Returns:
        The published Signal with assigned sequence number

    Examples:
        # From workflow code
        await emit("agent_comms", "task.created", {"task_id": "t1"})

        # Externally with explicit storage
        await emit("agent_comms", "task.created", payload, storage=my_storage)
    """
    # Resolve storage
    if storage is None:
        storage = _resolve_storage()

    if storage is None:
        raise RuntimeError(
            "No storage backend available. "
            "Either pass storage parameter or call pyworkflow.configure(storage=...)"
        )

    # Validate payload against schema if Pydantic model
    if isinstance(payload, BaseModel):
        payload_data = payload.model_dump()
    elif payload is None:
        payload_data = {}
    else:
        payload_data = payload

    # Resolve source run_id from context if available
    source_run_id = _get_source_run_id()

    # Resolve stream_run_id from context if not explicitly provided
    if stream_run_id is None:
        stream_run_id = _get_stream_run_id()

    # Create signal
    signal_id = f"sig_{uuid.uuid4().hex[:16]}"

    # Publish to storage
    sequence = await storage.publish_signal(
        signal_id=signal_id,
        stream_id=stream_id,
        signal_type=signal_type,
        payload=payload_data,
        source_run_id=source_run_id,
        stream_run_id=stream_run_id,
        metadata=metadata,
    )

    signal = Signal(
        signal_id=signal_id,
        stream_id=stream_id,
        signal_type=signal_type,
        payload=payload_data,
        sequence=sequence,
        source_run_id=source_run_id,
        stream_run_id=stream_run_id,
        metadata=metadata or {},
    )

    logger.info(
        f"Signal published: {signal_type} to {stream_id}",
        signal_id=signal_id,
        stream_id=stream_id,
        signal_type=signal_type,
        sequence=sequence,
    )

    # Record SIGNAL_PUBLISHED event in caller's workflow log (if in workflow context)
    if source_run_id:
        try:
            from pyworkflow.engine.events import create_signal_published_event

            event = create_signal_published_event(
                run_id=source_run_id,
                signal_id=signal_id,
                stream_id=stream_id,
                signal_type=signal_type,
            )
            await storage.record_event(event)
        except Exception:
            pass  # Non-critical: event logging is best-effort from caller context

    # Dispatch signal to waiting steps. Prefer enqueueing a celery task so
    # the parent worker (the one that called emit() from inside a workflow)
    # is not held while step lifecycles run; fall back to inline dispatch
    # for in-process / test environments where celery is unavailable.
    #
    # The InMemoryStorageBackend holds subscriptions in process-local state,
    # so a celery worker in a different process would not see them — always
    # dispatch inline for in-memory storage.
    dispatched_via_celery = False
    if storage.__class__.__name__ != "InMemoryStorageBackend":
        try:
            from pyworkflow.celery.tasks import dispatch_stream_signal_task
            from pyworkflow.storage.config import storage_to_config

            storage_config = storage_to_config(storage)
            dispatch_stream_signal_task.apply_async(
                kwargs={
                    "signal_id": signal_id,
                    "stream_id": stream_id,
                    "signal_type": signal_type,
                    "payload": payload_data,
                    "sequence": sequence,
                    "source_run_id": source_run_id,
                    "stream_run_id": stream_run_id,
                    "metadata": metadata or {},
                    "storage_config": storage_config,
                }
            )
            dispatched_via_celery = True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[emit] celery dispatch unavailable, falling back to inline: {e}")

    if not dispatched_via_celery:
        from pyworkflow.streams.dispatcher import dispatch_signal

        await dispatch_signal(signal, storage)

    return signal


async def schedule_signal(
    *,
    stream_id: str,
    signal_type: str,
    payload: Any = None,
    delay_seconds: float,
    stream_run_id: str | None = None,
    storage: Any = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Schedule a signal for future delivery.

    The signal row is persisted with a ``due_at`` timestamp; the
    :class:`StreamConsumer` polls ``fetch_due_scheduled_signals`` and calls
    :func:`emit` on each due row.

    Returns:
        The scheduled-signal ID.
    """
    from datetime import UTC, datetime, timedelta

    if storage is None:
        storage = _resolve_storage()
    if storage is None:
        raise RuntimeError(
            "No storage backend available for schedule_signal(). "
            "Either pass storage= or call pyworkflow.configure(storage=...)"
        )

    if isinstance(payload, BaseModel):
        payload_data = payload.model_dump()
    elif payload is None:
        payload_data = {}
    else:
        payload_data = payload

    if stream_run_id is None:
        stream_run_id = _get_stream_run_id()

    due_at = datetime.now(UTC) + timedelta(seconds=max(0.0, float(delay_seconds)))

    sched_id = await storage.schedule_signal(
        stream_id=stream_id,
        signal_type=signal_type,
        payload=payload_data,
        due_at=due_at,
        stream_run_id=stream_run_id,
        metadata=metadata,
    )
    logger.info(
        f"Signal scheduled: {signal_type} → {stream_id} in {delay_seconds}s",
        sched_id=sched_id,
        stream_id=stream_id,
        signal_type=signal_type,
    )
    return sched_id


def _resolve_storage() -> Any:
    """Try to resolve storage from workflow context or global config."""
    # Try workflow context first
    try:
        from pyworkflow.context import get_context, has_context

        if has_context():
            ctx = get_context()
            if hasattr(ctx, "_storage") and ctx._storage is not None:
                return ctx._storage
    except Exception:
        pass

    # Fall back to global config
    try:
        from pyworkflow.config import get_config

        config = get_config()
        return config.storage
    except Exception:
        return None


def _get_source_run_id() -> str | None:
    """Try to get the current workflow run_id from context."""
    try:
        from pyworkflow.context import get_context, has_context

        if has_context():
            ctx = get_context()
            return ctx.run_id
    except Exception:
        pass
    return None


def _get_stream_run_id() -> str | None:
    """Try to get the current stream_run_id from stream step context."""
    try:
        from pyworkflow.streams.context import get_stream_run_id

        return get_stream_run_id()
    except Exception:
        pass
    return None
