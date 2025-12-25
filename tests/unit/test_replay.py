"""
Unit tests for event replay engine.
"""

from datetime import UTC, datetime

import pytest

from pyworkflow.context import LocalContext
from pyworkflow.engine.events import (
    Event,
    EventType,
    create_hook_created_event,
    create_hook_expired_event,
    create_hook_received_event,
    create_sleep_completed_event,
    create_sleep_started_event,
    create_step_completed_event,
    create_step_started_event,
)
from pyworkflow.engine.replay import EventReplayer, replay_events
from pyworkflow.serialization.encoder import serialize
from pyworkflow.storage.file import FileStorageBackend


class TestEventReplayer:
    """Test the EventReplayer class."""

    @pytest.mark.asyncio
    async def test_replay_empty_events(self, tmp_path):
        """Test replaying with no events."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        replayer = EventReplayer()
        await replayer.replay(ctx, [])

        # Context should remain empty
        assert len(ctx.step_results) == 0
        assert len(ctx.completed_sleeps) == 0
        assert len(ctx.hook_results) == 0

    @pytest.mark.asyncio
    async def test_replay_step_completed(self, tmp_path):
        """Test replaying step.completed events."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        # Create step completed events
        events = [
            create_step_started_event(
                run_id="test_run",
                step_id="step_1",
                step_name="test_step",
                args="[]",
                kwargs="{}",
                attempt=1,
            ),
            create_step_completed_event(
                run_id="test_run",
                step_id="step_1",
                result=serialize("result_1"),
                step_name="test_step",
            ),
        ]

        # Assign sequence numbers
        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Step result should be cached
        assert "step_1" in ctx.step_results
        assert ctx.step_results["step_1"] == "result_1"

    @pytest.mark.asyncio
    async def test_replay_multiple_steps(self, tmp_path):
        """Test replaying multiple step events."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        events = [
            create_step_completed_event(
                run_id="test_run",
                step_id="step_1",
                result=serialize("result_1"),
                step_name="test_step",
            ),
            create_step_completed_event(
                run_id="test_run",
                step_id="step_2",
                result=serialize("result_2"),
                step_name="test_step",
            ),
            create_step_completed_event(
                run_id="test_run",
                step_id="step_3",
                result=serialize("result_3"),
                step_name="test_step",
            ),
        ]

        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # All results should be cached
        assert len(ctx.step_results) == 3
        assert ctx.step_results["step_1"] == "result_1"
        assert ctx.step_results["step_2"] == "result_2"
        assert ctx.step_results["step_3"] == "result_3"

    @pytest.mark.asyncio
    async def test_replay_sleep_events(self, tmp_path):
        """Test replaying sleep events."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        resume_at = datetime.now(UTC)
        events = [
            create_sleep_started_event(
                run_id="test_run",
                sleep_id="sleep_1",
                duration_seconds=60,
                resume_at=resume_at,
                name="test_sleep",
            ),
            create_sleep_completed_event(run_id="test_run", sleep_id="sleep_1"),
        ]

        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Sleep should be marked as completed
        assert ctx.is_sleep_completed("sleep_1")
        assert "sleep_1" in ctx.completed_sleeps

    @pytest.mark.asyncio
    async def test_replay_pending_sleep(self, tmp_path):
        """Test replaying sleep that hasn't completed."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        resume_at = datetime.now(UTC)
        events = [
            create_sleep_started_event(
                run_id="test_run",
                sleep_id="sleep_pending",
                duration_seconds=60,
                resume_at=resume_at,
                name="pending_sleep",
            ),
        ]

        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Sleep should be pending (not completed)
        assert not ctx.is_sleep_completed("sleep_pending")
        assert "sleep_pending" in ctx.pending_sleeps

    @pytest.mark.asyncio
    async def test_replay_hook_events(self, tmp_path):
        """Test replaying hook events."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        events = [
            create_hook_created_event(
                run_id="test_run",
                hook_id="hook_1",
                url="https://example.com/hook",
                token="secret_token",
                name="test_hook",
            ),
            create_hook_received_event(
                run_id="test_run",
                hook_id="hook_1",
                payload={"data": "test_payload"},
            ),
        ]

        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Hook result should be cached
        assert ctx.has_hook_result("hook_1")
        assert ctx.get_hook_result("hook_1") == {"data": "test_payload"}

    @pytest.mark.asyncio
    async def test_replay_expired_hook(self, tmp_path):
        """Test replaying an expired hook."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        events = [
            create_hook_created_event(
                run_id="test_run",
                hook_id="hook_expired",
                url="https://example.com/hook",
                token="token",
            ),
            create_hook_expired_event(
                run_id="test_run",
                hook_id="hook_expired",
            ),
        ]

        for i, event in enumerate(events, 1):
            event.sequence = i

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Hook should not be in pending hooks
        assert "hook_expired" not in ctx.pending_hooks
        # Hook should not have a result
        assert not ctx.has_hook_result("hook_expired")

    @pytest.mark.asyncio
    async def test_replay_events_in_order(self, tmp_path):
        """Test that events are replayed in sequence order."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        # Create events out of order
        event1 = create_step_completed_event(
            run_id="test_run", step_id="step_1", result=serialize("result_1"), step_name="test_step"
        )
        event1.sequence = 2

        event2 = create_step_completed_event(
            run_id="test_run", step_id="step_2", result=serialize("result_2"), step_name="test_step"
        )
        event2.sequence = 1

        # Provide in wrong order
        events = [event1, event2]

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Both should be replayed correctly regardless of input order
        assert len(ctx.step_results) == 2

    @pytest.mark.asyncio
    async def test_replay_sets_replaying_flag(self, tmp_path):
        """Test that replay sets and clears is_replaying flag."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        events = [
            create_step_completed_event(
                run_id="test_run",
                step_id="step_1",
                result=serialize("result"),
                step_name="test_step",
            ),
        ]
        events[0].sequence = 1

        assert ctx.is_replaying is False

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # After replay, flag should be cleared
        assert ctx.is_replaying is False


class TestReplayPublicAPI:
    """Test the public replay API."""

    @pytest.mark.asyncio
    async def test_replay_events_function(self, tmp_path):
        """Test the replay_events public function."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        events = [
            create_step_completed_event(
                run_id="test_run",
                step_id="step_1",
                result=serialize("test_result"),
                step_name="test_step",
            ),
        ]
        events[0].sequence = 1

        # Use public API
        await replay_events(ctx, events)

        # Verify replay worked
        assert "step_1" in ctx.step_results
        assert ctx.step_results["step_1"] == "test_result"


class TestReplayIntegration:
    """Integration tests for replay with full workflows."""

    @pytest.mark.asyncio
    async def test_replay_full_workflow(self, tmp_path):
        """Test replaying a complete workflow event log."""
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        # Simulate a workflow with steps and sleep
        resume_at = datetime.now(UTC)
        events = [
            Event(
                run_id="test_run",
                type=EventType.WORKFLOW_STARTED,
                sequence=1,
                data={"workflow_name": "test_workflow"},
            ),
            create_step_started_event(
                run_id="test_run",
                step_id="step_1",
                step_name="first_step",
                args="[]",
                kwargs="{}",
                attempt=1,
            ),
            create_step_completed_event(
                run_id="test_run",
                step_id="step_1",
                result=serialize("step_1_result"),
                step_name="first_step",
            ),
            create_sleep_started_event(
                run_id="test_run",
                sleep_id="sleep_1",
                duration_seconds=10,
                resume_at=resume_at,
            ),
            create_sleep_completed_event(run_id="test_run", sleep_id="sleep_1"),
            create_step_started_event(
                run_id="test_run",
                step_id="step_2",
                step_name="second_step",
                args="[]",
                kwargs="{}",
                attempt=1,
            ),
            create_step_completed_event(
                run_id="test_run",
                step_id="step_2",
                result=serialize("step_2_result"),
                step_name="second_step",
            ),
        ]

        # Assign sequences
        for i, event in enumerate(events, 1):
            event.sequence = i

        await replay_events(ctx, events)

        # Verify all state was restored
        assert len(ctx.step_results) == 2
        assert ctx.step_results["step_1"] == "step_1_result"
        assert ctx.step_results["step_2"] == "step_2_result"
        assert ctx.is_sleep_completed("sleep_1")
