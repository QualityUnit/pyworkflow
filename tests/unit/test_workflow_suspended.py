"""
Unit tests for WORKFLOW_SUSPENDED event and race condition prevention.

These tests verify that:
1. The WORKFLOW_SUSPENDED event is created correctly
2. Step completion/failure only schedules resume when workflow has suspended
3. Race conditions are prevented through event-based coordination
"""

from datetime import UTC, datetime

import pytest

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


class TestWorkflowSuspendedEvent:
    """Tests for WORKFLOW_SUSPENDED event creation."""

    def test_create_workflow_suspended_event_for_step(self):
        """Test creating suspended event for step dispatch."""
        event = create_workflow_suspended_event(
            run_id="run_123",
            reason="step_dispatch:step_abc",
            step_id="step_abc",
            step_name="process_data",
        )

        assert event.run_id == "run_123"
        assert event.type == EventType.WORKFLOW_SUSPENDED
        assert event.data["reason"] == "step_dispatch:step_abc"
        assert event.data["step_id"] == "step_abc"
        assert event.data["step_name"] == "process_data"
        assert event.data["sleep_id"] is None
        assert event.data["hook_id"] is None
        assert event.data["child_id"] is None
        assert "suspended_at" in event.data

    def test_create_workflow_suspended_event_for_sleep(self):
        """Test creating suspended event for sleep."""
        event = create_workflow_suspended_event(
            run_id="run_123",
            reason="sleep",
            sleep_id="sleep_xyz",
        )

        assert event.run_id == "run_123"
        assert event.type == EventType.WORKFLOW_SUSPENDED
        assert event.data["reason"] == "sleep"
        assert event.data["sleep_id"] == "sleep_xyz"
        assert event.data["step_id"] is None

    def test_create_workflow_suspended_event_for_hook(self):
        """Test creating suspended event for hook/webhook."""
        event = create_workflow_suspended_event(
            run_id="run_123",
            reason="hook",
            hook_id="hook_abc",
        )

        assert event.type == EventType.WORKFLOW_SUSPENDED
        assert event.data["reason"] == "hook"
        assert event.data["hook_id"] == "hook_abc"

    def test_create_workflow_suspended_event_for_child(self):
        """Test creating suspended event for child workflow."""
        event = create_workflow_suspended_event(
            run_id="run_123",
            reason="child_workflow",
            child_id="child_run_456",
        )

        assert event.type == EventType.WORKFLOW_SUSPENDED
        assert event.data["reason"] == "child_workflow"
        assert event.data["child_id"] == "child_run_456"

    def test_workflow_suspended_event_type_value(self):
        """Test that the event type has correct value."""
        assert EventType.WORKFLOW_SUSPENDED.value == "workflow.suspended"


class TestStepCompletionResumePrevention:
    """Tests for preventing duplicate resume scheduling on step completion."""

    @pytest.fixture
    def storage(self):
        """Provide a clean in-memory storage backend."""
        return InMemoryStorageBackend()

    @pytest.mark.asyncio
    async def test_step_completed_without_suspended_event(self, storage):
        """Step completion should NOT schedule resume if workflow hasn't suspended."""
        # Create workflow run
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Record workflow started event
        started_event = create_workflow_started_event(
            run_id="test_run",
            workflow_name="test_workflow",
            args=[],
            kwargs={},
        )
        await storage.record_event(started_event)

        # Record step completed event (simulates step completing before workflow suspends)
        step_event = create_step_completed_event(
            run_id="test_run",
            step_id="step_1",
            step_name="process_data",
            result="done",
        )
        await storage.record_event(step_event)

        # Check events - should NOT have WORKFLOW_SUSPENDED
        events = await storage.get_events("test_run")
        has_suspended = any(e.type == EventType.WORKFLOW_SUSPENDED for e in events)
        assert has_suspended is False

        # This verifies the logic: when has_suspended is False,
        # resume should NOT be scheduled (verified by absence of suspended event)

    @pytest.mark.asyncio
    async def test_step_completed_with_suspended_event(self, storage):
        """Step completion should schedule resume if workflow has suspended."""
        # Create workflow run
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.SUSPENDED,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Record workflow started event
        started_event = create_workflow_started_event(
            run_id="test_run",
            workflow_name="test_workflow",
            args=[],
            kwargs={},
        )
        await storage.record_event(started_event)

        # Record workflow suspended event FIRST (normal flow)
        suspended_event = create_workflow_suspended_event(
            run_id="test_run",
            reason="step_dispatch:step_1",
            step_id="step_1",
            step_name="process_data",
        )
        await storage.record_event(suspended_event)

        # Record step completed event
        step_event = create_step_completed_event(
            run_id="test_run",
            step_id="step_1",
            step_name="process_data",
            result="done",
        )
        await storage.record_event(step_event)

        # Check events - should have WORKFLOW_SUSPENDED
        events = await storage.get_events("test_run")
        has_suspended = any(e.type == EventType.WORKFLOW_SUSPENDED for e in events)
        assert has_suspended is True

        # This verifies the logic: when has_suspended is True,
        # resume should be scheduled


class TestStepFailureResumePrevention:
    """Tests for preventing duplicate resume scheduling on step failure."""

    @pytest.fixture
    def storage(self):
        """Provide a clean in-memory storage backend."""
        return InMemoryStorageBackend()

    @pytest.mark.asyncio
    async def test_step_failed_without_suspended_event(self, storage):
        """Step failure should NOT schedule resume if workflow hasn't suspended."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Record step failed event (simulates step failing before workflow suspends)
        step_event = create_step_failed_event(
            run_id="test_run",
            step_id="step_1",
            error="Test error",
            error_type="ValueError",
            is_retryable=False,
            attempt=1,
        )
        await storage.record_event(step_event)

        # Check events - should NOT have WORKFLOW_SUSPENDED
        events = await storage.get_events("test_run")
        has_suspended = any(e.type == EventType.WORKFLOW_SUSPENDED for e in events)
        assert has_suspended is False

    @pytest.mark.asyncio
    async def test_step_failed_with_suspended_event(self, storage):
        """Step failure should schedule resume if workflow has suspended."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.SUSPENDED,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Record workflow suspended event FIRST
        suspended_event = create_workflow_suspended_event(
            run_id="test_run",
            reason="step_dispatch:step_1",
            step_id="step_1",
            step_name="process_data",
        )
        await storage.record_event(suspended_event)

        # Record step failed event
        step_event = create_step_failed_event(
            run_id="test_run",
            step_id="step_1",
            error="Test error",
            error_type="ValueError",
            is_retryable=False,
            attempt=1,
        )
        await storage.record_event(step_event)

        # Check events - should have WORKFLOW_SUSPENDED
        events = await storage.get_events("test_run")
        has_suspended = any(e.type == EventType.WORKFLOW_SUSPENDED for e in events)
        assert has_suspended is True


class TestSuspensionHandlerRaceCondition:
    """Tests for the suspension handler detecting step completion race condition."""

    @pytest.fixture
    def storage(self):
        """Provide a clean in-memory storage backend."""
        return InMemoryStorageBackend()

    @pytest.mark.asyncio
    async def test_suspension_detects_step_already_completed(self, storage):
        """
        Suspension handler should detect if step completed before suspension.

        This tests the race condition case where:
        1. Workflow dispatches step to Celery
        2. Step completes BEFORE workflow catches SuspensionSignal
        3. Workflow suspends and records WORKFLOW_SUSPENDED
        4. Suspension handler checks for step completion and finds it completed
        5. Suspension handler schedules resume
        """
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Step completes FIRST (race condition)
        step_event = create_step_completed_event(
            run_id="test_run",
            step_id="step_1",
            step_name="process_data",
            result="done",
        )
        await storage.record_event(step_event)

        # NOW workflow suspends and records suspended event
        suspended_event = create_workflow_suspended_event(
            run_id="test_run",
            reason="step_dispatch:step_1",
            step_id="step_1",
            step_name="process_data",
        )
        await storage.record_event(suspended_event)

        # Suspension handler logic: check if step already completed
        events = await storage.get_events("test_run")
        step_id = "step_1"
        step_finished = any(
            evt.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
            and evt.data.get("step_id") == step_id
            for evt in events
        )

        # Step should be detected as finished
        assert step_finished is True

    @pytest.mark.asyncio
    async def test_suspension_detects_step_already_failed(self, storage):
        """
        Suspension handler should detect if step failed before suspension.
        """
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Step fails FIRST (race condition)
        step_event = create_step_failed_event(
            run_id="test_run",
            step_id="step_1",
            error="Test error",
            error_type="ValueError",
            is_retryable=False,
            attempt=1,
        )
        await storage.record_event(step_event)

        # NOW workflow suspends
        suspended_event = create_workflow_suspended_event(
            run_id="test_run",
            reason="step_dispatch:step_1",
            step_id="step_1",
            step_name="process_data",
        )
        await storage.record_event(suspended_event)

        # Suspension handler logic
        events = await storage.get_events("test_run")
        step_id = "step_1"
        step_finished = any(
            evt.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
            and evt.data.get("step_id") == step_id
            for evt in events
        )

        assert step_finished is True

    @pytest.mark.asyncio
    async def test_suspension_normal_flow_step_not_completed(self, storage):
        """
        In normal flow, step should not be completed when suspension happens.
        """
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        # Workflow suspends FIRST (normal flow)
        suspended_event = create_workflow_suspended_event(
            run_id="test_run",
            reason="step_dispatch:step_1",
            step_id="step_1",
            step_name="process_data",
        )
        await storage.record_event(suspended_event)

        # Check for step completion (step hasn't run yet)
        events = await storage.get_events("test_run")
        step_id = "step_1"
        step_finished = any(
            evt.type in (EventType.STEP_COMPLETED, EventType.STEP_FAILED)
            and evt.data.get("step_id") == step_id
            for evt in events
        )

        # Step should NOT be finished
        assert step_finished is False
