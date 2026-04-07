"""
Stream workflow runtime — aggregate lifecycle loop for @stream_workflow.

Replaces the no-op @stream_workflow body with a real runtime that:

1. Ensures DB subscriptions exist for every @stream_step registered on
   the stream name.
2. Runs the stream workflow body (and optional ``init`` callable) which
   typically emits a bootstrap signal.
3. Waits on an in-process asyncio.Event (keyed by ``stream_run_id``) that
   the dispatcher sets whenever a step's subscription status transitions.
4. After each transition computes the aggregate:
     - all terminated → return StreamWorkflowResult(status="completed")
     - any suspended (and none running) → raise SuspensionSignal, which
       propagates to the parent @workflow via the existing pyworkflow
       suspension mechanism.
     - otherwise → keep waiting.

The runtime is deterministic: on parent-workflow resume, ``run_stream_workflow``
re-derives state from storage subscriptions and continues.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.streams.dispatcher import _ensure_subscriptions_from_registry
from pyworkflow.streams.registry import get_steps_for_stream

# Module-level map: stream_run_id -> asyncio.Event
# Dispatcher pokes these whenever a subscription status changes.
_runtime_waiters: dict[str, asyncio.Event] = {}


def _get_or_create_waiter(stream_run_id: str) -> asyncio.Event:
    ev = _runtime_waiters.get(stream_run_id)
    if ev is None:
        ev = asyncio.Event()
        _runtime_waiters[stream_run_id] = ev
    return ev


def notify_runtime(stream_run_id: str | None) -> None:
    """Wake any ``run_stream_workflow`` loop waiting on this stream run."""
    if not stream_run_id:
        return
    ev = _runtime_waiters.get(stream_run_id)
    if ev is not None:
        ev.set()


@dataclass
class StreamWorkflowResult:
    """Result of a completed stream workflow run."""

    status: str  # "completed"
    step_states: dict[str, str] = field(default_factory=dict)


def _resolve_stream_name(stream_workflow_func: Any) -> str:
    name = getattr(stream_workflow_func, "__stream_name__", None)
    if name:
        return str(name)
    return str(getattr(stream_workflow_func, "__name__", "stream"))


def _resolve_storage() -> Any:
    try:
        from pyworkflow.context import get_context, has_context

        if has_context():
            ctx = get_context()
            if getattr(ctx, "_storage", None) is not None:
                return ctx._storage
    except Exception:  # noqa: BLE001 — best-effort fallback
        pass
    try:
        from pyworkflow.config import get_config

        return get_config().storage
    except Exception:  # noqa: BLE001
        return None


def _compute_aggregate(states: list[dict]) -> tuple[str, list[str]]:
    """Compute aggregate status and list of suspended step_run_ids.

    Returns (aggregate, suspended_step_run_ids). Aggregate is one of:
    "completed" (all terminated), "suspended" (>=1 suspended, none running),
    "running" (at least one running/waiting).
    """
    if not states:
        return "running", []

    running = [s for s in states if s["status"] in ("running",)]
    waiting = [s for s in states if s["status"] == "waiting"]
    suspended = [s for s in states if s["status"] == "suspended"]
    terminated = [s for s in states if s["status"] in ("terminated", "completed")]

    if len(terminated) == len(states):
        return "completed", []
    if running:
        return "running", [s["step_run_id"] for s in suspended]
    if suspended and not waiting:
        return "suspended", [s["step_run_id"] for s in suspended]
    return "running", [s["step_run_id"] for s in suspended]


async def run_stream_workflow(
    stream_workflow_func: Any,
    *,
    stream_run_id: str,
    init: Callable[[], Awaitable[None]] | None = None,
    storage: Any = None,
    poll_interval: float = 2.0,
) -> StreamWorkflowResult:
    """Drive a stream workflow to completion.

    See module docstring for semantics.

    Args:
        stream_workflow_func: The ``@stream_workflow`` decorated function.
        stream_run_id: Unique identifier for this stream-workflow run;
            used both for subscription scoping and the in-process waiter.
        init: Optional async callable invoked before the aggregate loop
            (typically emits the bootstrap signal).
        storage: Storage backend (auto-resolved from context/config).
        poll_interval: Fallback poll interval in seconds; the runtime
            normally wakes on dispatcher notifications, but we still
            re-scan storage periodically as a safety net.
    """
    if storage is None:
        storage = _resolve_storage()
    if storage is None:
        raise RuntimeError(
            "No storage backend available for run_stream_workflow(). "
            "Call pyworkflow.configure(storage=...) first."
        )

    stream_name = _resolve_stream_name(stream_workflow_func)

    # Ensure a DB subscription exists for every @stream_step on this stream.
    # We query the registry directly and call _ensure_subscriptions_from_registry
    # per signal_type so rows materialize even if no signals have been emitted.
    registered = get_steps_for_stream(stream_name)
    for step_meta in registered:
        signal_types = step_meta.signal_types or []
        if not signal_types:
            continue
        # Use the first signal type — _ensure_subscriptions_from_registry
        # creates one row per step regardless of which signal_type we pass.
        try:
            await _ensure_subscriptions_from_registry(stream_name, signal_types[0], storage)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"[run_stream_workflow] failed to ensure subscription for "
                f"step {step_meta.name}: {e}"
            )

    waiter = _get_or_create_waiter(stream_run_id)
    waiter.clear()

    # Background poller: drain due scheduled_signals while the runtime is alive.
    # Without this, schedule_signal() rows never fire (no separate consumer).
    scheduled_task = asyncio.create_task(
        _scheduled_signal_poller(storage, poll_interval)
    )

    # Run the stream workflow body (init hook + decorated function).
    try:
        if init is not None:
            await init()
        if stream_workflow_func is not None:
            await stream_workflow_func()
    except Exception:  # noqa: BLE001
        logger.exception(f"[run_stream_workflow] body raised for {stream_name}")
        raise

    # Aggregate loop.
    try:
        while True:
            try:
                states = await storage.get_subscription_states(stream_name, stream_run_id)
            except NotImplementedError:
                # Storage doesn't support the new method — fall back to
                # acting as a no-op marker (legacy behavior).
                logger.warning(
                    "[run_stream_workflow] storage backend does not support "
                    "get_subscription_states; treating as completed"
                )
                return StreamWorkflowResult(status="completed")

            aggregate, suspended_ids = _compute_aggregate(states)

            if aggregate == "completed":
                logger.info(
                    f"[run_stream_workflow] {stream_name} completed (stream_run_id={stream_run_id})"
                )
                return StreamWorkflowResult(
                    status="completed",
                    step_states={s["step_run_id"]: s["status"] for s in states},
                )

            if aggregate == "suspended":
                reason_tag = f"stream_step_suspended:{stream_name}"
                logger.info(
                    f"[run_stream_workflow] {stream_name} suspended (steps={suspended_ids})"
                )
                raise SuspensionSignal(
                    reason_tag,
                    stream_name=stream_name,
                    stream_run_id=stream_run_id,
                    suspended_step_run_ids=suspended_ids,
                )

            # aggregate == "running" — wait for notification or poll tick.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(waiter.wait(), timeout=poll_interval)
            waiter.clear()
    finally:
        scheduled_task.cancel()
        with contextlib.suppress(BaseException):
            await scheduled_task


async def _scheduled_signal_poller(storage: Any, interval: float) -> None:
    """Periodically drain due scheduled_signals and emit them."""
    from datetime import UTC, datetime

    from pyworkflow.streams.emit import emit

    while True:
        try:
            now = datetime.now(UTC)
            try:
                due = await storage.fetch_due_scheduled_signals(now, limit=50)
            except NotImplementedError:
                return  # backend doesn't support scheduled signals — bail out
            for row in due or []:
                try:
                    await emit(
                        stream_id=row["stream_id"],
                        signal_type=row["signal_type"],
                        payload=row.get("payload") or {},
                        storage=storage,
                        stream_run_id=row.get("stream_run_id"),
                        metadata=row.get("metadata") or {},
                    )
                    await storage.mark_scheduled_signal_delivered(row["id"])
                except Exception as e:  # noqa: BLE001
                    logger.error(
                        f"[scheduled_signal_poller] failed to deliver "
                        f"{row.get('id')}: {e}"
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[scheduled_signal_poller] error: {e}")
        await asyncio.sleep(interval)
