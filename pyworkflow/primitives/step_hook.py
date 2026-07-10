"""
Hook primitive for use within @step functions.

Allows steps to suspend and wait for external events (human-in-the-loop,
approvals, external API callbacks), then resume with the hook payload.

Unlike workflow-level hook(), step_hook() works from within steps by:
1. Checking if the hook result is already available (replay/re-execution)
2. If not, creating a hook in storage and raising SuspensionSignal
3. On resume, the step re-executes and step_hook() returns the cached result

Usage:
    @step
    async def agent_step():
        checkpoint = await load_step_checkpoint()
        if checkpoint:
            state = checkpoint["state"]
        else:
            state = await init_agent()
            await save_step_checkpoint({"state": state})

        # Suspends step until hook is called externally
        human_input = await step_hook("human_review")
        return await process(state, human_input)
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel

from pyworkflow.context import get_context, has_context
from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.primitives.step_checkpoint import get_step_id, get_step_name, get_step_run_id


class StepHookTimeout:
    """Sentinel returned by ``step_hook(on_timeout="return")`` when the hook expires.

    Check with ``isinstance(result, StepHookTimeout)`` or compare against the
    ``STEP_HOOK_TIMEOUT`` singleton.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "STEP_HOOK_TIMEOUT"


STEP_HOOK_TIMEOUT = StepHookTimeout()


async def step_hook(
    name: str,
    *,
    timeout: str | int | None = None,
    on_created: Callable[[str], Awaitable[None]] | None = None,
    payload_schema: type[BaseModel] | None = None,
    on_timeout: Literal["suspend", "return"] = "suspend",
) -> Any:
    """
    Wait for an external event from within a @step function.

    Creates a hook and suspends the step. When resume_hook() is called
    with the token, the step is re-executed and step_hook() returns
    the payload from the hook.

    The step function MUST be idempotent: it will re-execute from the
    beginning on resume. Use save_step_checkpoint() / load_step_checkpoint()
    to persist state across suspensions.

    Args:
        name: Human-readable name for the hook
        timeout: Optional max wait time (str duration or seconds)
        on_created: Optional async callback with the hook token
        payload_schema: Optional Pydantic model for payload validation
        on_timeout: What to do when ``timeout`` elapses without a resume.
            "suspend" (default): keep waiting for resume_hook() — legacy behavior.
            "return": the runtime schedules a resume at the deadline and this
            call returns the ``STEP_HOOK_TIMEOUT`` sentinel on re-execution.

    Returns:
        Payload from resume_hook(), or ``STEP_HOOK_TIMEOUT`` when the hook
        expired and ``on_timeout="return"``

    Raises:
        RuntimeError: If called outside a step context

    Example:
        @step
        async def review_step():
            await save_step_checkpoint({"draft": "..."})

            async def notify(token):
                await send_to_reviewer(token)

            feedback = await step_hook("review", on_created=notify)
            return feedback
    """
    if not has_context():
        raise RuntimeError(
            "step_hook() must be called within a @step function running in a workflow context."
        )

    ctx = get_context()
    storage = ctx._storage if hasattr(ctx, "_storage") else None

    if storage is None:
        raise RuntimeError("step_hook() requires durable mode with a storage backend.")

    # Get step execution context
    step_run_id = get_step_run_id()
    if step_run_id is None:
        raise RuntimeError(
            "step_hook() must be called within a @step function. "
            "Use hook() for workflow-level hooks."
        )

    # Identify the step in the event log. The engine records a STEP_SUSPENDED
    # event from the SuspensionSignal below (so replay does not treat the step
    # as still in progress), and that event must carry the *deterministic*
    # step id — not the composite "run_id:step_id" checkpoint key. Prefer the
    # id/name plumbed through the step execution context; fall back to stripping
    # the run_id prefix off step_run_id for callers that did not provide them.
    signal_step_id = get_step_id()
    if signal_step_id is None:
        prefix = f"{ctx.run_id}:"
        signal_step_id = (
            step_run_id[len(prefix) :] if step_run_id.startswith(prefix) else step_run_id
        )
    signal_step_name = get_step_name()

    # Generate deterministic hook_id based on step_run_id and hook name
    # This ensures the same hook call gets the same ID on re-execution
    hook_counter = getattr(ctx, "_step_hook_counter", 0)
    ctx._step_hook_counter = hook_counter + 1  # type: ignore[attr-defined]
    hook_id = f"step_hook_{name}_{hook_counter}"

    # Check if hook result is already available (from previous execution)
    # Look for HOOK_RECEIVED event with this hook_id
    from pyworkflow.engine.events import EventType

    events = await storage.get_events(ctx.run_id)
    hook_received = None
    hook_created_event = None

    for event in events:
        if event.type == EventType.HOOK_CREATED and event.data.get("hook_id") == hook_id:
            hook_created_event = event
        elif event.type == EventType.HOOK_RECEIVED and event.data.get("hook_id") == hook_id:
            hook_received = event

    # If hook was already received, return the payload (replay)
    if hook_received is not None:
        from pyworkflow.serialization.decoder import deserialize

        payload = deserialize(hook_received.data.get("payload"))
        logger.debug(
            f"Step hook '{name}' already received, returning cached payload",
            run_id=ctx.run_id,
            hook_id=hook_id,
        )
        return payload

    # If hook was already created but not received, check expiry, else re-suspend
    if hook_created_event is not None:
        expires_at: datetime | None = None
        expires_at_raw = hook_created_event.data.get("expires_at")
        if expires_at_raw:
            expires_at = datetime.fromisoformat(expires_at_raw)

        if on_timeout == "return" and expires_at is not None and datetime.now(UTC) >= expires_at:
            from pyworkflow.engine.events import create_hook_expired_event
            from pyworkflow.storage.schemas import HookStatus

            await storage.record_event(
                create_hook_expired_event(run_id=ctx.run_id, hook_id=hook_id)
            )
            try:
                await storage.update_hook_status(hook_id, HookStatus.EXPIRED)
            except Exception:
                # Best-effort: the HOOK_EXPIRED event is authoritative for replay;
                # a failed status update must not fail the step.
                logger.warning(
                    f"Step hook '{name}' expired but status update failed",
                    run_id=ctx.run_id,
                    hook_id=hook_id,
                )
            logger.info(
                f"Step hook '{name}' expired, returning timeout sentinel",
                run_id=ctx.run_id,
                hook_id=hook_id,
            )
            return STEP_HOOK_TIMEOUT

        logger.debug(
            f"Step hook '{name}' already created, re-suspending",
            run_id=ctx.run_id,
            hook_id=hook_id,
        )
        # Re-arm the deadline resume only for on_timeout="return" with a future
        # deadline: the runtime schedules a resume at resume_at, and scheduling
        # one in the past would busy-loop resume → re-suspend.
        resume_data: dict[str, Any] = {}
        if on_timeout == "return" and expires_at is not None and datetime.now(UTC) < expires_at:
            resume_data["resume_at"] = expires_at
        raise SuspensionSignal(
            reason=f"step_hook:{hook_id}",
            hook_id=hook_id,
            step_id=signal_step_id,
            step_name=signal_step_name,
            **resume_data,
        )

    # Parse timeout
    timeout_seconds: int | None = None
    if timeout is not None:
        if isinstance(timeout, str):
            from pyworkflow.utils.duration import parse_duration

            timeout_seconds = parse_duration(timeout)
        else:
            timeout_seconds = int(timeout)

    # Create the hook token
    from pyworkflow.primitives.resume_hook import create_hook_token

    token = create_hook_token(ctx.run_id, hook_id)

    # Record HOOK_CREATED event
    from pyworkflow.engine.events import create_hook_created_event

    hook_event = create_hook_created_event(
        run_id=ctx.run_id,
        hook_id=hook_id,
        token=token,
        timeout_seconds=timeout_seconds,
        name=name,
    )
    await storage.record_event(hook_event)

    # Create hook record in storage
    from pyworkflow.storage.schemas import Hook, HookStatus

    hook_record = Hook(
        hook_id=hook_id,
        run_id=ctx.run_id,
        name=name,
        token=token,
        status=HookStatus.PENDING,
        payload_schema=payload_schema.__name__ if payload_schema else None,
    )
    if timeout_seconds:
        hook_record.expires_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds)

    await storage.create_hook(hook_record)

    logger.info(
        f"Step hook created: '{name}'",
        run_id=ctx.run_id,
        hook_id=hook_id,
        token=token,
        step_run_id=step_run_id,
    )

    # Call on_created callback if provided
    if on_created:
        await on_created(token)

    # Raise SuspensionSignal to suspend the step. For on_timeout="return",
    # carry the deadline so the runtime schedules a resume at expiry — without
    # it, an expired hook nobody resumes would suspend the workflow forever.
    suspend_data: dict[str, Any] = {}
    if on_timeout == "return" and hook_record.expires_at is not None:
        suspend_data["resume_at"] = hook_record.expires_at
    raise SuspensionSignal(
        reason=f"step_hook:{hook_id}",
        hook_id=hook_id,
        step_id=signal_step_id,
        step_name=signal_step_name,
        **suspend_data,
    )
