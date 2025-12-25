"""
Integration tests for fault tolerance features.

Tests cover the full workflow recovery flow after simulated worker failures.
"""

from datetime import UTC, datetime

import pytest

from pyworkflow import (
    reset_config,
    workflow,
)
from pyworkflow.engine.events import (
    EventType,
    create_step_completed_event,
    create_workflow_interrupted_event,
    create_workflow_started_event,
)
from pyworkflow.serialization.encoder import serialize, serialize_args, serialize_kwargs
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


class TestRecoveryDetection:
    """Tests for detecting recovery scenarios."""

    @pytest.mark.asyncio
    async def test_detect_running_workflow_as_recovery_scenario(self, storage):
        """A workflow in RUNNING status should be detected as recovery scenario."""
        # Create a workflow run that's stuck in RUNNING (simulates worker crash)
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
            recovery_attempts=0,
            max_recovery_attempts=3,
            recover_on_worker_loss=True,
        )
        await storage.create_run(run)

        # Verify the run is in RUNNING status
        retrieved_run = await storage.get_run("test_run")
        assert retrieved_run.status == RunStatus.RUNNING
        assert retrieved_run.recover_on_worker_loss is True

    @pytest.mark.asyncio
    async def test_recovery_disabled_workflow(self, storage):
        """Workflow with recover_on_worker_loss=False should not auto-recover."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
            recovery_attempts=0,
            max_recovery_attempts=3,
            recover_on_worker_loss=False,  # Disabled
        )
        await storage.create_run(run)

        retrieved_run = await storage.get_run("test_run")
        assert retrieved_run.recover_on_worker_loss is False


class TestInterruptedEventRecording:
    """Tests for recording WORKFLOW_INTERRUPTED events."""

    @pytest.mark.asyncio
    async def test_record_interrupted_event(self, storage):
        """Should record WORKFLOW_INTERRUPTED event on recovery."""
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
        start_event = create_workflow_started_event(
            run_id="test_run",
            workflow_name="test_workflow",
            args=serialize_args(),
            kwargs=serialize_kwargs(),
        )
        await storage.record_event(start_event)

        # Record step completed event
        step_event = create_step_completed_event(
            run_id="test_run",
            step_id="step_1",
            result=serialize(42),
            step_name="test_step",
        )
        await storage.record_event(step_event)

        # Simulate worker crash - record interrupted event
        interrupted_event = create_workflow_interrupted_event(
            run_id="test_run",
            reason="worker_lost",
            worker_id="worker_1",
            last_event_sequence=2,
            error="Worker process terminated",
            recovery_attempt=1,
            recoverable=True,
        )
        await storage.record_event(interrupted_event)

        # Verify events
        events = await storage.get_events("test_run")
        assert len(events) == 3

        # Check interrupted event
        interrupted = [e for e in events if e.type == EventType.WORKFLOW_INTERRUPTED]
        assert len(interrupted) == 1
        assert interrupted[0].data["reason"] == "worker_lost"
        assert interrupted[0].data["recovery_attempt"] == 1


class TestRecoveryAttemptTracking:
    """Tests for tracking recovery attempts."""

    @pytest.mark.asyncio
    async def test_increment_recovery_attempts(self, storage):
        """Should increment recovery_attempts on each recovery."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
            recovery_attempts=0,
            max_recovery_attempts=3,
        )
        await storage.create_run(run)

        # First recovery attempt
        await storage.update_run_recovery_attempts("test_run", 1)
        run1 = await storage.get_run("test_run")
        assert run1.recovery_attempts == 1

        # Second recovery attempt
        await storage.update_run_recovery_attempts("test_run", 2)
        run2 = await storage.get_run("test_run")
        assert run2.recovery_attempts == 2

        # Third recovery attempt
        await storage.update_run_recovery_attempts("test_run", 3)
        run3 = await storage.get_run("test_run")
        assert run3.recovery_attempts == 3

    @pytest.mark.asyncio
    async def test_max_recovery_attempts_exceeded(self, storage):
        """Should mark workflow as FAILED when max attempts exceeded."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
            recovery_attempts=3,  # Already at max
            max_recovery_attempts=3,
        )
        await storage.create_run(run)

        # Simulating what would happen when max exceeded
        await storage.update_run_status(
            run_id="test_run",
            status=RunStatus.FAILED,
            error="Exceeded max recovery attempts (3)",
        )

        run = await storage.get_run("test_run")
        assert run.status == RunStatus.FAILED
        assert "max recovery attempts" in run.error.lower()


class TestEventReplayWithInterruption:
    """Tests for event replay after interruption."""

    @pytest.mark.asyncio
    async def test_replay_preserves_step_results_after_interruption(self, storage):
        """Step results should be preserved and replayable after interruption."""
        from pyworkflow.context import LocalContext
        from pyworkflow.engine.replay import replay_events

        # Create events simulating a workflow that was interrupted
        events = [
            create_workflow_started_event(
                run_id="test_run",
                workflow_name="test_workflow",
                args=serialize_args("arg1"),
                kwargs=serialize_kwargs(key="value"),
            ),
            create_step_completed_event(
                run_id="test_run",
                step_id="step_1",
                result=serialize({"processed": True}),
                step_name="step_1",
            ),
            create_step_completed_event(
                run_id="test_run",
                step_id="step_2",
                result=serialize(100),
                step_name="step_2",
            ),
            create_workflow_interrupted_event(
                run_id="test_run",
                reason="worker_lost",
                recovery_attempt=1,
            ),
        ]

        # Assign sequence numbers
        for i, event in enumerate(events):
            event.sequence = i + 1
            await storage.record_event(event)

        # Load events and replay
        loaded_events = await storage.get_events("test_run")

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            event_log=loaded_events,
            durable=True,
        )

        await replay_events(ctx, loaded_events)

        # Verify step results are available
        assert ctx.get_step_result("step_1") == {"processed": True}
        assert ctx.get_step_result("step_2") == 100


class TestStatusTransitions:
    """Tests for workflow status transitions during recovery."""

    @pytest.mark.asyncio
    async def test_running_to_interrupted(self, storage):
        """RUNNING -> INTERRUPTED transition."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
        await storage.create_run(run)

        await storage.update_run_status(
            run_id="test_run",
            status=RunStatus.INTERRUPTED,
        )

        run = await storage.get_run("test_run")
        assert run.status == RunStatus.INTERRUPTED

    @pytest.mark.asyncio
    async def test_interrupted_to_running_on_recovery(self, storage):
        """INTERRUPTED -> RUNNING transition on recovery."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.INTERRUPTED,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
            recovery_attempts=1,
        )
        await storage.create_run(run)

        # Recovery starts
        await storage.update_run_status(
            run_id="test_run",
            status=RunStatus.RUNNING,
        )

        run = await storage.get_run("test_run")
        assert run.status == RunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_interrupted_to_failed_on_max_attempts(self, storage):
        """INTERRUPTED -> FAILED when max attempts exceeded."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.INTERRUPTED,
            created_at=datetime.now(UTC),
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
            recovery_attempts=3,
            max_recovery_attempts=3,
        )
        await storage.create_run(run)

        await storage.update_run_status(
            run_id="test_run",
            status=RunStatus.FAILED,
            error="Exceeded max recovery attempts",
        )

        run = await storage.get_run("test_run")
        assert run.status == RunStatus.FAILED


class TestWorkflowDecoratorRecoveryConfig:
    """Tests for workflow decorator recovery configuration."""

    def test_workflow_decorator_stores_recovery_config(self):
        """@workflow decorator should store recovery config on wrapper."""

        @workflow(
            name="test_recovery_config_1",
            recover_on_worker_loss=True,
            max_recovery_attempts=5,
        )
        async def my_workflow():
            pass

        assert my_workflow.__workflow_recover_on_worker_loss__ is True
        assert my_workflow.__workflow_max_recovery_attempts__ == 5

    def test_workflow_decorator_defaults_none(self):
        """@workflow decorator should default recovery config to None when called with ()."""

        @workflow(name="test_recovery_config_2")
        async def my_workflow():
            pass

        assert my_workflow.__workflow_recover_on_worker_loss__ is None
        assert my_workflow.__workflow_max_recovery_attempts__ is None

    def test_workflow_decorator_disable_recovery(self):
        """@workflow decorator can disable recovery."""

        @workflow(name="test_recovery_config_3", recover_on_worker_loss=False)
        async def my_workflow():
            pass

        assert my_workflow.__workflow_recover_on_worker_loss__ is False
