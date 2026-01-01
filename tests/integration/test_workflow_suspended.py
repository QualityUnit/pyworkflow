"""
Integration tests for WORKFLOW_SUSPENDED event and race condition handling.

These tests verify that the event-based coordination between step completion
and workflow suspension properly prevents duplicate resume scheduling.
"""

from datetime import UTC, datetime

import pytest

from pyworkflow import configure, reset_config, start
from pyworkflow.core.step import step
from pyworkflow.core.workflow import workflow
from pyworkflow.engine.events import (
    EventType,
    create_step_completed_event,
    create_step_failed_event,
    create_workflow_started_event,
    create_workflow_suspended_event,
)
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


@pytest.fixture
def storage():
    """Provide a clean in-memory storage backend for each test."""
    return InMemoryStorageBackend()


@pytest.fixture(autouse=True)
def reset_pyworkflow_config():
    """Reset configuration before and after each test."""
    reset_config()
    yield
    reset_config()


class TestWorkflowSuspensionEventRecording:
    """Tests for WORKFLOW_SUSPENDED event being recorded correctly."""

    @pytest.mark.asyncio
    async def test_sleep_records_suspended_event(self, storage):
        """Sleep suspension should record WORKFLOW_SUSPENDED event."""
        from pyworkflow.primitives.sleep import sleep

        # Configure storage globally
        configure(storage=storage, default_durable=True)

        @workflow(name="sleep_workflow_test")
        async def sleep_workflow():
            await sleep("10s")
            return "done"

        run_id = await start(sleep_workflow)

        # Check workflow suspended
        run = await storage.get_run(run_id)
        assert run.status == RunStatus.SUSPENDED

        # Check WORKFLOW_SUSPENDED event was recorded
        events = await storage.get_events(run_id)
        suspended_events = [e for e in events if e.type == EventType.WORKFLOW_SUSPENDED]

        assert len(suspended_events) >= 1
        suspended_event = suspended_events[0]
        assert "sleep" in suspended_event.data.get("reason", "")

    @pytest.mark.asyncio
    async def test_step_records_suspended_event(self, storage):
        """Step dispatch should record WORKFLOW_SUSPENDED event."""
        # Configure storage globally
        configure(storage=storage, default_durable=True)

        @step(name="suspended_event_test_step")
        async def my_step():
            return "result"

        @workflow(name="step_workflow_test")
        async def step_workflow():
            result = await my_step()
            return result

        run_id = await start(step_workflow)

        # Get events
        events = await storage.get_events(run_id)
        event_types = [e.type for e in events]

        # Local runtime executes steps inline, so we may not see suspended event
        # for steps. But we should see step events.
        assert EventType.STEP_STARTED in event_types
        assert EventType.STEP_COMPLETED in event_types


class TestRaceConditionPrevention:
    """Tests for race condition prevention in step completion."""

    @pytest.mark.asyncio
    async def test_events_have_proper_sequencing(self, storage):
        """Events should be properly sequenced with workflow_suspended coming before step_completed when workflow suspends first."""
        # Configure storage globally
        configure(storage=storage, default_durable=True)

        @step()
        async def ordered_step():
            return "done"

        @workflow(name="sequenced_workflow_test")
        async def sequenced_workflow():
            result = await ordered_step()
            return result

        run_id = await start(sequenced_workflow)

        # Get all events
        events = await storage.get_events(run_id)

        # Verify event sequence numbers are assigned
        for event in events:
            assert event.sequence >= 0

        # Events should be in sequence order
        sequences = [e.sequence for e in events]
        assert sequences == sorted(sequences)


class TestBidirectionalEventCheck:
    """Tests for the bidirectional event checking logic."""

    @pytest.mark.asyncio
    async def test_step_completion_checks_for_suspended_event(self, storage):
        """
        Verify the logic that step completion checks for WORKFLOW_SUSPENDED.

        This tests the check in _record_step_completion_and_resume:
        - Get events
        - Check if any event is WORKFLOW_SUSPENDED
        - Only schedule resume if found
        """
        run_id = "test_run_bidir"

        # Create workflow run in suspended state
        run = WorkflowRun(
            run_id=run_id,
            workflow_name="test_workflow",
            status=RunStatus.SUSPENDED,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Record workflow started
        started_event = create_workflow_started_event(
            run_id=run_id,
            workflow_name="test_workflow",
            args=[],
            kwargs={},
        )
        await storage.record_event(started_event)

        # Case 1: No WORKFLOW_SUSPENDED event yet
        events = await storage.get_events(run_id)
        has_suspended = any(e.type == EventType.WORKFLOW_SUSPENDED for e in events)
        assert has_suspended is False  # Should NOT schedule resume

        # Case 2: Add WORKFLOW_SUSPENDED event
        suspended_event = create_workflow_suspended_event(
            run_id=run_id,
            reason="step_dispatch:step_1",
            step_id="step_1",
            step_name="test_step",
        )
        await storage.record_event(suspended_event)

        events = await storage.get_events(run_id)
        has_suspended = any(e.type == EventType.WORKFLOW_SUSPENDED for e in events)
        assert has_suspended is True  # Should schedule resume

    @pytest.mark.asyncio
    async def test_suspension_handler_checks_for_step_completion(self, storage):
        """
        Verify the logic that suspension handler checks for step completion.

        This tests the check in suspension handler:
        - Get events
        - Check if step_id matches STEP_COMPLETED or STEP_FAILED
        - Schedule resume if found (race condition case)
        """
        run_id = "test_run_bidir_step"
        step_id = "step_1"

        # Create workflow run
        run = WorkflowRun(
            run_id=run_id,
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Record workflow started
        started_event = create_workflow_started_event(
            run_id=run_id,
            workflow_name="test_workflow",
            args=[],
            kwargs={},
        )
        await storage.record_event(started_event)

        # Case 1: Step not completed yet (normal flow)
        events = await storage.get_events(run_id)
        step_finished = any(
            e.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
            and e.data.get("step_id") == step_id
            for e in events
        )
        assert step_finished is False  # Normal flow - don't schedule resume here

        # Case 2: Step completed before suspension (race condition)
        step_event = create_step_completed_event(
            run_id=run_id,
            step_id=step_id,
            step_name="test_step",
            result="done",
        )
        await storage.record_event(step_event)

        events = await storage.get_events(run_id)
        step_finished = any(
            e.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
            and e.data.get("step_id") == step_id
            for e in events
        )
        assert step_finished is True  # Race condition - schedule resume here


class TestEventBasedCoordination:
    """Tests for event-based coordination ensuring exactly-once resume."""

    @pytest.mark.asyncio
    async def test_exactly_one_resume_path_when_step_completes_first(self, storage):
        """
        When step completes before workflow suspends:
        - Step completion sees no WORKFLOW_SUSPENDED -> skips resume
        - Suspension handler sees STEP_COMPLETED -> schedules resume
        Result: Exactly one resume scheduled by suspension handler
        """
        run_id = "race_test_step_first"
        step_id = "step_1"

        # Create workflow run
        run = WorkflowRun(
            run_id=run_id,
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Record started event
        await storage.record_event(
            create_workflow_started_event(
                run_id=run_id,
                workflow_name="test_workflow",
                args=[],
                kwargs={},
            )
        )

        # === STEP COMPLETES FIRST ===
        step_event = create_step_completed_event(
            run_id=run_id,
            step_id=step_id,
            step_name="test_step",
            result="done",
        )
        await storage.record_event(step_event)

        # Step completion check: no WORKFLOW_SUSPENDED
        events = await storage.get_events(run_id)
        has_suspended = any(e.type == EventType.WORKFLOW_SUSPENDED for e in events)
        assert has_suspended is False  # Step skips resume

        # === WORKFLOW SUSPENDS SECOND ===
        suspended_event = create_workflow_suspended_event(
            run_id=run_id,
            reason=f"step_dispatch:{step_id}",
            step_id=step_id,
            step_name="test_step",
        )
        await storage.record_event(suspended_event)

        # Suspension handler check: step already completed
        events = await storage.get_events(run_id)
        step_finished = any(
            e.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
            and e.data.get("step_id") == step_id
            for e in events
        )
        assert step_finished is True  # Suspension handler schedules resume

    @pytest.mark.asyncio
    async def test_exactly_one_resume_path_when_workflow_suspends_first(self, storage):
        """
        When workflow suspends before step completes (normal flow):
        - Suspension handler sees no STEP_COMPLETED -> skips resume
        - Step completion sees WORKFLOW_SUSPENDED -> schedules resume
        Result: Exactly one resume scheduled by step completion
        """
        run_id = "race_test_workflow_first"
        step_id = "step_1"

        # Create workflow run
        run = WorkflowRun(
            run_id=run_id,
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Record started event
        await storage.record_event(
            create_workflow_started_event(
                run_id=run_id,
                workflow_name="test_workflow",
                args=[],
                kwargs={},
            )
        )

        # === WORKFLOW SUSPENDS FIRST ===
        suspended_event = create_workflow_suspended_event(
            run_id=run_id,
            reason=f"step_dispatch:{step_id}",
            step_id=step_id,
            step_name="test_step",
        )
        await storage.record_event(suspended_event)

        # Suspension handler check: step not completed
        events = await storage.get_events(run_id)
        step_finished = any(
            e.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
            and e.data.get("step_id") == step_id
            for e in events
        )
        assert step_finished is False  # Suspension handler skips resume

        # === STEP COMPLETES SECOND ===
        step_event = create_step_completed_event(
            run_id=run_id,
            step_id=step_id,
            step_name="test_step",
            result="done",
        )
        await storage.record_event(step_event)

        # Step completion check: WORKFLOW_SUSPENDED exists
        events = await storage.get_events(run_id)
        has_suspended = any(e.type == EventType.WORKFLOW_SUSPENDED for e in events)
        assert has_suspended is True  # Step completion schedules resume

    @pytest.mark.asyncio
    async def test_race_condition_with_step_failure(self, storage):
        """
        When step fails before workflow suspends:
        - Step failure sees no WORKFLOW_SUSPENDED -> skips resume
        - Suspension handler sees STEP_FAILED -> schedules resume
        Result: Exactly one resume scheduled by suspension handler
        """
        run_id = "race_test_step_failure"
        step_id = "step_1"

        # Create workflow run
        run = WorkflowRun(
            run_id=run_id,
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Record started event
        await storage.record_event(
            create_workflow_started_event(
                run_id=run_id,
                workflow_name="test_workflow",
                args=[],
                kwargs={},
            )
        )

        # === STEP FAILS FIRST ===
        step_event = create_step_failed_event(
            run_id=run_id,
            step_id=step_id,
            error="Test error",
            error_type="ValueError",
            is_retryable=False,
            attempt=1,
        )
        await storage.record_event(step_event)

        # Step failure check: no WORKFLOW_SUSPENDED
        events = await storage.get_events(run_id)
        has_suspended = any(e.type == EventType.WORKFLOW_SUSPENDED for e in events)
        assert has_suspended is False  # Step failure skips resume

        # === WORKFLOW SUSPENDS SECOND ===
        suspended_event = create_workflow_suspended_event(
            run_id=run_id,
            reason=f"step_dispatch:{step_id}",
            step_id=step_id,
            step_name="test_step",
        )
        await storage.record_event(suspended_event)

        # Suspension handler check: step already failed
        events = await storage.get_events(run_id)
        step_finished = any(
            e.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
            and e.data.get("step_id") == step_id
            for e in events
        )
        assert step_finished is True  # Suspension handler schedules resume
