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
from typing import Any

from loguru import logger
from pydantic import BaseModel

from pyworkflow.context import get_context, has_context
from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.primitives.step_checkpoint import get_step_run_id


async def step_hook(
    name: str,
    *,
    timeout: str | int | None = None,
    on_created: Callable[[str], Awaitable[None]] | None = None,
    payload_schema: type[BaseModel] | None = None,
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

    Returns:
        Payload from resume_hook()

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
    hook_created = False

    for event in events:
        if event.type == EventType.HOOK_CREATED and event.data.get("hook_id") == hook_id:
            hook_created = True
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

    # If hook was already created but not received, re-suspend
    if hook_created:
        logger.debug(
            f"Step hook '{name}' already created, re-suspending",
            run_id=ctx.run_id,
            hook_id=hook_id,
        )
        raise SuspensionSignal(
            reason=f"step_hook:{hook_id}",
            hook_id=hook_id,
            step_id=step_run_id,
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
        from datetime import UTC, datetime, timedelta

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

    # Raise SuspensionSignal to suspend the step
    raise SuspensionSignal(
        reason=f"step_hook:{hook_id}",
        hook_id=hook_id,
        step_id=step_run_id,
    )
