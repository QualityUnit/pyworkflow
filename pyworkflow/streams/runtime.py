"""
Stream workflow runtime — hook-based aggregate lifecycle for @stream_workflow.

The parent @workflow calls ``await run_stream_workflow(...)`` from inside its
durable context. This function:

1. Ensures DB subscriptions exist for every @stream_step on this stream.
2. On the FIRST execution (gated by replay-safe ``hook()`` semantics), runs
   the optional ``init`` callable and the stream-workflow body.
3. Computes the current aggregate state from storage:
     - "completed" → return ``StreamWorkflowResult``
     - "suspended" → raise ``SuspensionSignal`` (HITL bubble-up)
     - otherwise → ``await hook(name=f"stream:{stream_run_id}", on_created=...)``
       which suspends the parent workflow via the existing pyworkflow
       hook primitive. The parent worker is released; resumption happens
       only when the dispatcher calls ``resume_hook()`` on the recorded
       token after a step transition causes the aggregate to become
       terminal.

This file no longer maintains any in-process waiter map and no longer runs
a background scheduled-signal poller — the celery beat task
``pyworkflow.streams.drain_scheduled_signals`` owns that responsibility.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.streams.dispatcher import _ensure_subscriptions_from_registry
from pyworkflow.streams.registry import get_steps_for_stream


@dataclass
class StreamWorkflowResult:
    """Result of a completed stream workflow run.

    ``step_results`` carries any payloads that stream steps published via
    ``set_result()`` from their lifecycle body. Keyed by ``step_run_id``,
    which encodes the step name (``stream_step_{name}_{stream_run_id}``).
    Use :meth:`get_result` for a name-based lookup.
    """

    status: str  # "completed"
    step_states: dict[str, str] = field(default_factory=dict)
    step_results: dict[str, Any] = field(default_factory=dict)

    def get_result(self, step_name: str) -> Any:
        """Return the result published by the step with the given name,
        or ``None`` if it didn't publish one."""
        for sid, value in self.step_results.items():
            if step_name in sid:
                return value
        return None


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
            ctx_storage = getattr(ctx, "_storage", None)
            if ctx_storage is not None:
                return ctx_storage
    except Exception:  # noqa: BLE001
        pass
    try:
        from pyworkflow.config import get_config

        return get_config().storage
    except Exception:  # noqa: BLE001
        return None


def _compute_aggregate(states: list[dict]) -> tuple[str, list[str]]:
    """Compute aggregate status from subscription rows.

    Returns (aggregate, suspended_step_run_ids). Aggregate is one of:
    "completed" (all terminated), "suspended" (>=1 suspended, none running),
    "running" (still active).
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


async def _ensure_all_subscriptions(stream_name: str, storage: Any, stream_run_id: str) -> None:
    """Materialize a DB subscription row per @stream_step on this stream run."""
    for step_meta in get_steps_for_stream(stream_name):
        signal_types = step_meta.signal_types or []
        if not signal_types:
            continue
        try:
            await _ensure_subscriptions_from_registry(
                stream_name, signal_types[0], storage, stream_run_id=stream_run_id
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"[run_stream_workflow] failed to ensure subscription for "
                f"step {step_meta.name}: {e}"
            )


async def run_stream_workflow(
    stream_workflow_func: Any,
    *,
    stream_run_id: str,
    init: Callable[[], Awaitable[None]] | None = None,
    storage: Any = None,
    poll_interval: float = 2.0,  # kept for API compatibility; unused
) -> StreamWorkflowResult:
    """Drive a stream workflow to completion via hook-based suspension.

    The parent worker is released between step dispatches: this function
    ``await``s a ``hook()`` whose token is recorded against the stream run.
    The stream-step dispatcher calls ``resume_hook()`` when the aggregate
    becomes terminal, which re-enqueues the parent workflow on a fresh
    worker.
    """
    if storage is None:
        storage = _resolve_storage()
    if storage is None:
        raise RuntimeError(
            "No storage backend available for run_stream_workflow(). "
            "Call pyworkflow.configure(storage=...) first."
        )

    stream_name = _resolve_stream_name(stream_workflow_func)

    # Aggregate-first: handles the resume path (hook payload returned).
    # Cheap query; runs on every replay so terminal states short-circuit.
    try:
        states = await storage.get_subscription_states(stream_name, stream_run_id)
    except NotImplementedError:
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
            step_results={
                s["step_run_id"]: s.get("result") for s in states if s.get("result") is not None
            },
        )

    if aggregate == "suspended":
        logger.info(f"[run_stream_workflow] {stream_name} suspended (steps={suspended_ids})")
        raise SuspensionSignal(
            f"stream_step_suspended:{stream_name}",
            stream_name=stream_name,
            stream_run_id=stream_run_id,
            suspended_step_run_ids=suspended_ids,
        )

    # First-run path: no terminal state yet. Make sure subscriptions exist
    # and run init+body. On replay, ``hook()`` below short-circuits via
    # ``_pending_hooks``/``_hook_results`` so init+body do NOT re-run unless
    # the parent has not yet reached the hook call site (which is impossible
    # because hook() is the first ContextVar write after init+body).
    # We still gate init+body on whether any subscription rows exist for
    # this stream_run_id, to be safe across cold replays.
    if not states:
        await _ensure_all_subscriptions(stream_name, storage, stream_run_id)
        try:
            if init is not None:
                await init()
            if stream_workflow_func is not None:
                await stream_workflow_func()
        except Exception:
            logger.exception(f"[run_stream_workflow] body raised for {stream_name}")
            raise

        # Re-check aggregate after body — body may have driven everything
        # to terminal synchronously (e.g. tests, no-op streams).
        states = await storage.get_subscription_states(stream_name, stream_run_id)
        aggregate, suspended_ids = _compute_aggregate(states)
        if aggregate == "completed":
            return StreamWorkflowResult(
                status="completed",
                step_states={s["step_run_id"]: s["status"] for s in states},
            )
        if aggregate == "suspended":
            raise SuspensionSignal(
                f"stream_step_suspended:{stream_name}",
                stream_name=stream_name,
                stream_run_id=stream_run_id,
                suspended_step_run_ids=suspended_ids,
            )

    # Suspend the parent via hook() — released worker until dispatcher resumes us.
    from pyworkflow.context import get_context
    from pyworkflow.primitives.hooks import hook

    parent_run_id = get_context().run_id

    async def _on_created(token: str) -> None:
        # Persist (parent_run_id, hook_token) on every subscription for this
        # stream run, then re-check the aggregate. If the dispatcher already
        # drove the stream to terminal between our aggregate check above and
        # the hook creation, we self-resume so we don't deadlock.
        try:
            await storage.set_stream_parent_link(
                stream_id=stream_name,
                stream_run_id=stream_run_id,
                parent_run_id=parent_run_id,
                parent_hook_token=token,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[run_stream_workflow] failed to persist parent link: {e}")
            return

        try:
            states_now = await storage.get_subscription_states(stream_name, stream_run_id)
            agg_now, _ = _compute_aggregate(states_now)
            if agg_now in ("completed", "suspended"):
                from pyworkflow.primitives.resume_hook import resume_hook

                await resume_hook(token, {"aggregate": agg_now}, storage=storage)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[run_stream_workflow] race-check resume failed: {e}")

    await hook(name=f"stream:{stream_run_id}", on_created=_on_created)

    # Resumed: recompute and return / re-raise.
    states = await storage.get_subscription_states(stream_name, stream_run_id)
    aggregate, suspended_ids = _compute_aggregate(states)

    if aggregate == "suspended":
        raise SuspensionSignal(
            f"stream_step_suspended:{stream_name}",
            stream_name=stream_name,
            stream_run_id=stream_run_id,
            suspended_step_run_ids=suspended_ids,
        )

    return StreamWorkflowResult(
        status="completed" if aggregate == "completed" else "running",
        step_states={s["step_run_id"]: s["status"] for s in states},
    )
