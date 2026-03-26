"""
Signal dispatcher for matching signals to subscribed stream steps.

When a signal is published, the dispatcher:
1. Finds all stream steps subscribed to the signal type
2. Invokes their on_signal callbacks
3. If ctx.resume() was called, triggers workflow resume
"""

from typing import Any

from loguru import logger
from pydantic import ValidationError

from pyworkflow.streams.registry import get_steps_for_stream, list_stream_steps
from pyworkflow.streams.signal import Signal
from pyworkflow.streams.step_context import StreamStepContext


async def dispatch_signal(signal: Signal, storage: Any) -> None:
    """
    Dispatch a signal to all subscribed stream steps.

    1. Find steps subscribed to this signal_type on this stream
    2. Validate payload against schema if defined
    3. Invoke on_signal callback for each
    4. If ctx.resume() was called, trigger workflow resume

    Args:
        signal: The published signal
        storage: Storage backend
    """
    # Find waiting steps from storage
    waiting_steps = await storage.get_waiting_steps(signal.stream_id, signal.signal_type)

    # Fallback: if no DB subscriptions exist, auto-register from in-memory registry.
    # Only do this if there are also no subscriptions in ANY status (e.g. "running")
    # to avoid creating duplicate subscriptions when a step is currently executing.
    if not waiting_steps:
        all_subs = await storage.get_subscriptions_for_stream(signal.stream_id, signal.signal_type)
        if not all_subs:
            waiting_steps = await _ensure_subscriptions_from_registry(
                signal.stream_id, signal.signal_type, storage
            )

    if not waiting_steps:
        logger.debug(
            f"No waiting steps for {signal.signal_type} on {signal.stream_id}",
            stream_id=signal.stream_id,
            signal_type=signal.signal_type,
        )
        return

    for step_info in waiting_steps:
        step_run_id = step_info["step_run_id"]

        try:
            await _dispatch_to_step(signal, step_run_id, storage)
        except Exception as e:
            logger.error(
                f"Error dispatching signal to step {step_run_id}: {e}",
                signal_id=signal.signal_id,
                step_run_id=step_run_id,
            )


async def _dispatch_to_step(
    signal: Signal,
    step_run_id: str,
    storage: Any,
) -> None:
    """
    Dispatch a signal to a specific stream step.

    Args:
        signal: The signal to dispatch
        step_run_id: The target step's run ID
        storage: Storage backend
    """
    # Find the stream step metadata by looking up the step name
    # The step_run_id format encodes the step name
    step_meta = _find_step_metadata_for_run(step_run_id, signal.stream_id)

    if step_meta is None:
        logger.warning(
            f"No registered stream step found for run {step_run_id}",
            step_run_id=step_run_id,
        )
        # Still acknowledge the signal even without metadata
        await storage.acknowledge_signal(signal.signal_id, step_run_id)
        return

    # Validate payload against schema if defined
    validated_signal = signal
    if signal.signal_type in step_meta.signal_schemas:
        schema_class = step_meta.signal_schemas[signal.signal_type]
        try:
            validated_payload = schema_class.model_validate(signal.payload)
            validated_signal = Signal(
                signal_id=signal.signal_id,
                stream_id=signal.stream_id,
                signal_type=signal.signal_type,
                payload=validated_payload,
                published_at=signal.published_at,
                sequence=signal.sequence,
                source_run_id=signal.source_run_id,
                metadata=signal.metadata,
            )
        except ValidationError as e:
            logger.error(
                f"Signal payload validation failed for {signal.signal_type}: {e}",
                signal_id=signal.signal_id,
                signal_type=signal.signal_type,
            )
            await storage.acknowledge_signal(signal.signal_id, step_run_id)
            return

    # Create StreamStepContext for the callback
    ctx = StreamStepContext(
        status="suspended",
        run_id=step_run_id,
        stream_id=signal.stream_id,
        storage=storage,
    )

    # Invoke the on_signal callback
    try:
        await step_meta.on_signal(validated_signal, ctx)
    except Exception as e:
        logger.error(
            f"on_signal callback error for step {step_run_id}: {e}",
            signal_id=signal.signal_id,
            step_run_id=step_run_id,
        )

    # Acknowledge signal
    await storage.acknowledge_signal(signal.signal_id, step_run_id)

    # Record SIGNAL_RECEIVED event
    try:
        from pyworkflow.engine.events import create_signal_received_event
        from pyworkflow.serialization.encoder import serialize

        event = create_signal_received_event(
            run_id=step_run_id,
            signal_id=signal.signal_id,
            stream_id=signal.stream_id,
            signal_type=signal.signal_type,
            payload=serialize(signal.payload),
        )
        await storage.record_event(event)
    except Exception:
        pass  # Best-effort event logging

    # Handle cancellation
    if ctx.is_cancelled:
        await _cancel_step(step_run_id, ctx.cancel_reason, storage)
        return

    # If resume was requested, trigger workflow resume
    if ctx.should_resume:
        await _resume_step(step_run_id, validated_signal, storage)


async def _resume_step(
    step_run_id: str,
    signal: Signal,
    storage: Any,
) -> None:
    """
    Execute a stream step's lifecycle function after on_signal called ctx.resume().

    Unlike workflow resumption, stream steps don't have a WorkflowRun record.
    Instead, we directly execute the lifecycle function with the proper
    stream step context (signal, checkpoint, storage).
    """
    from pyworkflow.streams.context import reset_stream_step_context, set_stream_step_context

    logger.info(
        f"Executing stream step {step_run_id}",
        step_run_id=step_run_id,
        signal_type=signal.signal_type,
    )

    # Update subscription status to running
    await storage.update_subscription_status(signal.stream_id, step_run_id, "running")

    # Find the step's lifecycle function from the registry
    step_meta = _find_step_metadata_for_run(step_run_id, signal.stream_id)
    if step_meta is None:
        logger.warning(
            f"No registered stream step found for run {step_run_id}, cannot execute",
            step_run_id=step_run_id,
        )
        return

    # Set up stream step context so get_current_signal(), get_checkpoint(),
    # save_checkpoint() work inside the lifecycle function
    tokens = set_stream_step_context(
        step_run_id=step_run_id,
        stream_id=signal.stream_id,
        signal=signal,
        storage=storage,
    )

    try:
        await step_meta.func()
    except Exception as e:
        logger.error(
            f"Stream step lifecycle error for {step_run_id}: {e}",
            step_run_id=step_run_id,
            exc_info=True,
        )
    finally:
        reset_stream_step_context(tokens)

    # Return subscription to waiting status for next signal
    try:
        await storage.update_subscription_status(signal.stream_id, step_run_id, "waiting")
    except Exception:
        pass  # Best-effort


async def _cancel_step(
    step_run_id: str,
    reason: str | None,
    storage: Any,
) -> None:
    """Cancel a stream step."""
    logger.info(
        f"Cancelling stream step {step_run_id}",
        step_run_id=step_run_id,
        reason=reason,
    )

    try:
        from pyworkflow.engine.events import create_stream_step_completed_event
        from pyworkflow.storage.schemas import RunStatus

        # Record completion event
        event = create_stream_step_completed_event(
            run_id=step_run_id,
            stream_id="",  # Will be filled from context
            step_name="",
            reason=f"cancelled: {reason}" if reason else "cancelled",
        )
        await storage.record_event(event)

        # Update run status
        await storage.update_run_status(step_run_id, RunStatus.CANCELLED)
    except Exception as e:
        logger.error(f"Error cancelling stream step: {e}", step_run_id=step_run_id)


async def _ensure_subscriptions_from_registry(
    stream_id: str,
    signal_type: str,
    storage: Any,
) -> list[dict]:
    """Auto-register DB subscriptions from the in-memory registry.

    When @stream_step decorated functions are registered in memory but
    no corresponding DB subscription exists, create one and return it
    so dispatch_signal can proceed.
    """
    import uuid

    registered_steps = get_steps_for_stream(stream_id)
    created = []

    for step_meta in registered_steps:
        if signal_type not in step_meta.signal_types:
            continue

        step_run_id = f"stream_step_{step_meta.name}_{uuid.uuid4().hex[:12]}"

        try:
            await storage.register_stream_subscription(
                stream_id=stream_id,
                step_run_id=step_run_id,
                signal_types=step_meta.signal_types,
            )
            created.append({
                "stream_id": stream_id,
                "step_run_id": step_run_id,
                "signal_types": step_meta.signal_types,
                "status": "waiting",
            })
            logger.info(
                f"Auto-registered stream subscription for step '{step_meta.name}' "
                f"on stream '{stream_id}'",
                step_run_id=step_run_id,
            )
        except Exception as e:
            logger.error(
                f"Failed to auto-register subscription for step '{step_meta.name}': {e}",
                stream_id=stream_id,
            )

    return created


def _find_step_metadata_for_run(step_run_id: str, stream_id: str) -> Any:
    """Find registered stream step metadata for a given run and stream."""
    all_steps = list_stream_steps()
    for step_meta in all_steps.values():
        if step_meta.stream == stream_id:
            # Check if the step_run_id matches this step's pattern
            # step_run_ids encode the step name: "stream_step_{step_name}_{uuid}"
            if step_meta.name in step_run_id:
                return step_meta
    # Fallback: return the first step on this stream that subscribes to this signal
    for step_meta in all_steps.values():
        if step_meta.stream == stream_id:
            return step_meta
    return None
