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

from pyworkflow.streams.registry import list_stream_steps
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
    Resume a stream step's lifecycle after on_signal called ctx.resume().

    This follows the same pattern as resume_hook().
    """
    logger.info(
        f"Resuming stream step {step_run_id}",
        step_run_id=step_run_id,
        signal_type=signal.signal_type,
    )

    # Update subscription status to running
    await storage.update_subscription_status(signal.stream_id, step_run_id, "running")

    # Schedule workflow resumption via configured runtime
    try:
        from pyworkflow.config import get_config
        from pyworkflow.runtime import get_runtime

        config = get_config()
        runtime = get_runtime(config.default_runtime)
        await runtime.schedule_resume(step_run_id, storage)
    except Exception as e:
        logger.warning(
            f"Failed to schedule stream step resumption: {e}",
            step_run_id=step_run_id,
        )


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
