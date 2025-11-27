"""
Event replay engine for deterministic workflow state reconstruction.

The replay engine processes the event log to rebuild workflow state,
enabling fault tolerance and resumption after crashes or suspensions.
"""

from typing import List

from loguru import logger

from pyworkflow.core.context import WorkflowContext
from pyworkflow.engine.events import Event, EventType


class EventReplayer:
    """
    Replays events to reconstruct workflow state.

    The replayer processes events in sequence order to restore:
    - Completed step results
    - Hook payloads
    - Sleep completion status
    """

    async def replay(self, ctx: WorkflowContext, events: List[Event]) -> None:
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
            f"{len(ctx.pending_sleeps)} pending sleeps",
            run_id=ctx.run_id,
        )

    async def _apply_event(self, ctx: WorkflowContext, event: Event) -> None:
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

        # Other event types don't affect replay state
        # (workflow_started, step_started, etc. are informational)

    async def _apply_step_completed(self, ctx: WorkflowContext, event: Event) -> None:
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

    async def _apply_sleep_started(self, ctx: WorkflowContext, event: Event) -> None:
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

    async def _apply_sleep_completed(self, ctx: WorkflowContext, event: Event) -> None:
        """Apply sleep_completed event - mark sleep as done."""
        sleep_id = event.data.get("sleep_id")

        if sleep_id:
            ctx.mark_sleep_completed(sleep_id)
            logger.debug(
                f"Sleep completed: {sleep_id}",
                run_id=ctx.run_id,
                sleep_id=sleep_id,
            )

    async def _apply_hook_created(self, ctx: WorkflowContext, event: Event) -> None:
        """Apply hook_created event - mark hook as pending."""
        hook_id = event.data.get("hook_id")

        if hook_id:
            ctx.add_pending_hook(hook_id, event.data)
            logger.debug(
                f"Hook pending: {hook_id}",
                run_id=ctx.run_id,
                hook_id=hook_id,
            )

    async def _apply_hook_received(self, ctx: WorkflowContext, event: Event) -> None:
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

    async def _apply_hook_expired(self, ctx: WorkflowContext, event: Event) -> None:
        """Apply hook_expired event - remove from pending."""
        hook_id = event.data.get("hook_id")

        if hook_id:
            ctx.pending_hooks.pop(hook_id, None)
            logger.debug(
                f"Hook expired: {hook_id}",
                run_id=ctx.run_id,
                hook_id=hook_id,
            )


# Singleton instance
_replayer = EventReplayer()


async def replay_events(ctx: WorkflowContext, events: List[Event]) -> None:
    """
    Replay events to restore workflow state.

    Public API for event replay.

    Args:
        ctx: Workflow context to populate
        events: List of events to replay
    """
    await _replayer.replay(ctx, events)
