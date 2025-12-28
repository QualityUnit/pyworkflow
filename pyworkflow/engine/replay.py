"""
Event replay engine for deterministic workflow state reconstruction.

The replay engine processes the event log to rebuild workflow state,
enabling fault tolerance and resumption after crashes or suspensions.
"""

from loguru import logger

from pyworkflow.context import LocalContext
from pyworkflow.engine.events import Event, EventType


class EventReplayer:
    """
    Replays events to reconstruct workflow state.

    The replayer processes events in sequence order to restore:
    - Completed step results
    - Hook payloads
    - Sleep completion status
    """

    async def replay(self, ctx: LocalContext, events: list[Event]) -> None:
        """
        Replay events to restore workflow state.

        This enables deterministic execution - same events always produce
        same state.

        Args:
            ctx: Workflow context to populate
            events: List of events ordered by sequence
        """
        if not events:
            logger.debug(f"No events to replay for run {ctx.run_id}")
            return

        logger.debug(
            f"Replaying {len(events)} events for run {ctx.run_id}",
            run_id=ctx.run_id,
            workflow_name=ctx.workflow_name,
        )

        ctx.is_replaying = True
        ctx.event_log = events

        for event in sorted(events, key=lambda e: e.sequence or 0):
            await self._apply_event(ctx, event)

        ctx.is_replaying = False

        logger.debug(
            f"Replay complete: {len(ctx.step_results)} steps, "
            f"{len(ctx.hook_results)} hooks, "
            f"{len(ctx.pending_sleeps)} pending sleeps, "
            f"{len(ctx.retry_state)} pending retries",
            run_id=ctx.run_id,
        )

    async def _apply_event(self, ctx: LocalContext, event: Event) -> None:
        """
        Apply a single event to the context.

        Args:
            ctx: Workflow context
            event: Event to apply
        """
        if event.type == EventType.STEP_COMPLETED:
            await self._apply_step_completed(ctx, event)

        elif event.type == EventType.SLEEP_STARTED:
            await self._apply_sleep_started(ctx, event)

        elif event.type == EventType.SLEEP_COMPLETED:
            await self._apply_sleep_completed(ctx, event)

        elif event.type == EventType.HOOK_CREATED:
            await self._apply_hook_created(ctx, event)

        elif event.type == EventType.HOOK_RECEIVED:
            await self._apply_hook_received(ctx, event)

        elif event.type == EventType.HOOK_EXPIRED:
            await self._apply_hook_expired(ctx, event)

        elif event.type == EventType.STEP_RETRYING:
            await self._apply_step_retrying(ctx, event)

        elif event.type == EventType.WORKFLOW_INTERRUPTED:
            await self._apply_workflow_interrupted(ctx, event)

        elif event.type == EventType.CANCELLATION_REQUESTED:
            await self._apply_cancellation_requested(ctx, event)

        elif event.type == EventType.CONTEXT_UPDATED:
            await self._apply_context_updated(ctx, event)

        # Other event types don't affect replay state
        # (workflow_started, step_started, step_failed, etc. are informational)

    async def _apply_step_completed(self, ctx: LocalContext, event: Event) -> None:
        """Apply step_completed event - cache the result."""
        from pyworkflow.serialization.decoder import deserialize

        step_id = event.data.get("step_id")
        result_json = event.data.get("result")

        if step_id and result_json:
            # Deserialize the result before caching
            result = deserialize(result_json)
            ctx.cache_step_result(step_id, result)
            logger.debug(
                f"Cached step result: {step_id}",
                run_id=ctx.run_id,
                step_id=step_id,
            )

    async def _apply_sleep_started(self, ctx: LocalContext, event: Event) -> None:
        """Apply sleep_started event - mark sleep as pending."""
        from datetime import datetime

        sleep_id = event.data.get("sleep_id")
        resume_at_str = event.data.get("resume_at")

        if sleep_id and resume_at_str:
            # Parse resume_at from ISO format
            resume_at = datetime.fromisoformat(resume_at_str)
            ctx.add_pending_sleep(sleep_id, resume_at)
            logger.debug(
                f"Sleep pending: {sleep_id}",
                run_id=ctx.run_id,
                sleep_id=sleep_id,
                resume_at=resume_at_str,
            )

    async def _apply_sleep_completed(self, ctx: LocalContext, event: Event) -> None:
        """Apply sleep_completed event - mark sleep as done."""
        sleep_id = event.data.get("sleep_id")

        if sleep_id:
            ctx.mark_sleep_completed(sleep_id)
            logger.debug(
                f"Sleep completed: {sleep_id}",
                run_id=ctx.run_id,
                sleep_id=sleep_id,
            )

    async def _apply_hook_created(self, ctx: LocalContext, event: Event) -> None:
        """Apply hook_created event - mark hook as pending."""
        hook_id = event.data.get("hook_id")

        if hook_id:
            ctx.add_pending_hook(hook_id, event.data)
            logger.debug(
                f"Hook pending: {hook_id}",
                run_id=ctx.run_id,
                hook_id=hook_id,
            )

    async def _apply_hook_received(self, ctx: LocalContext, event: Event) -> None:
        """Apply hook_received event - cache the payload."""
        hook_id = event.data.get("hook_id")
        payload = event.data.get("payload")

        if hook_id:
            ctx.cache_hook_result(hook_id, payload)
            logger.debug(
                f"Cached hook result: {hook_id}",
                run_id=ctx.run_id,
                hook_id=hook_id,
            )

    async def _apply_hook_expired(self, ctx: LocalContext, event: Event) -> None:
        """Apply hook_expired event - remove from pending."""
        hook_id = event.data.get("hook_id")

        if hook_id:
            ctx.pending_hooks.pop(hook_id, None)
            logger.debug(
                f"Hook expired: {hook_id}",
                run_id=ctx.run_id,
                hook_id=hook_id,
            )

    async def _apply_step_retrying(self, ctx: LocalContext, event: Event) -> None:
        """Apply step_retrying event - restore retry state for resumption."""
        from datetime import datetime

        step_id = event.data.get("step_id")
        next_attempt = event.data.get("attempt")
        resume_at_str = event.data.get("resume_at")
        event.data.get("retry_after")
        max_retries = event.data.get("max_retries", 3)
        retry_delay = event.data.get("retry_strategy", "exponential")
        last_error = event.data.get("error", "")

        if step_id and next_attempt:
            # Parse resume_at from ISO format
            resume_at = datetime.fromisoformat(resume_at_str) if resume_at_str else None

            # Restore retry state to context
            ctx.set_retry_state(
                step_id=step_id,
                attempt=next_attempt,
                resume_at=resume_at,
                max_retries=max_retries,
                retry_delay=retry_delay,
                last_error=last_error,
            )

            logger.debug(
                f"Retry pending: {step_id}",
                run_id=ctx.run_id,
                step_id=step_id,
                next_attempt=next_attempt,
                resume_at=resume_at_str,
            )

    async def _apply_workflow_interrupted(self, ctx: LocalContext, event: Event) -> None:
        """
        Apply workflow_interrupted event - log the interruption.

        This event is informational for the replay - it doesn't change state
        since the workflow will continue from the last completed step.
        The event records that an interruption occurred for auditing purposes.
        """
        reason = event.data.get("reason", "unknown")
        recovery_attempt = event.data.get("recovery_attempt", 0)
        last_event_sequence = event.data.get("last_event_sequence")

        logger.info(
            f"Workflow was interrupted: {reason}",
            run_id=ctx.run_id,
            reason=reason,
            recovery_attempt=recovery_attempt,
            last_event_sequence=last_event_sequence,
        )

    async def _apply_cancellation_requested(self, ctx: LocalContext, event: Event) -> None:
        """
        Apply cancellation_requested event - mark workflow for cancellation.

        This event signals that cancellation was requested. During replay,
        we set the cancellation flag so the workflow will raise CancellationError
        at the next check point.
        """
        reason = event.data.get("reason")
        requested_by = event.data.get("requested_by")

        # Set cancellation flag in context
        ctx.request_cancellation(reason=reason)

        logger.info(
            "Cancellation requested for workflow",
            run_id=ctx.run_id,
            reason=reason,
            requested_by=requested_by,
        )

    async def _apply_context_updated(self, ctx: LocalContext, event: Event) -> None:
        """
        Apply context_updated event - restore step context.

        During replay, this restores the step context to its state at the time
        the event was recorded. This ensures deterministic replay.
        """
        from pyworkflow.context.step_context import (
            _set_step_context_internal,
            get_step_context_class,
        )

        context_data = event.data.get("context", {})

        if context_data:
            # Get the registered context class
            context_class = get_step_context_class()
            if context_class is not None:
                try:
                    step_ctx = context_class.from_dict(context_data)
                    _set_step_context_internal(step_ctx)
                    logger.debug(
                        "Restored step context from replay",
                        run_id=ctx.run_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to restore step context: {e}",
                        run_id=ctx.run_id,
                    )
            else:
                logger.debug(
                    "No context class registered, skipping context restoration",
                    run_id=ctx.run_id,
                )


# Singleton instance
_replayer = EventReplayer()


async def replay_events(ctx: LocalContext, events: list[Event]) -> None:
    """
    Replay events to restore workflow state.

    Public API for event replay.

    Args:
        ctx: Workflow context to populate
        events: List of events to replay
    """
    await _replayer.replay(ctx, events)
