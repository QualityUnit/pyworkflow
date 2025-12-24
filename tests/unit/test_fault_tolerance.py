"""
Unit tests for fault tolerance features.

Tests cover:
- WORKFLOW_INTERRUPTED event type
- RunStatus.INTERRUPTED status
- WorkflowRun recovery tracking fields
- Replay mechanism handling of WORKFLOW_INTERRUPTED
- Recovery config options
"""

from datetime import UTC, datetime

import pytest

from pyworkflow.config import PyWorkflowConfig
from pyworkflow.engine.events import (
    Event,
    EventType,
    create_workflow_interrupted_event,
)
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


class TestWorkflowInterruptedEvent:
    """Tests for WORKFLOW_INTERRUPTED event type."""

    def test_event_type_exists(self):
        """WORKFLOW_INTERRUPTED should be defined in EventType."""
        assert hasattr(EventType, "WORKFLOW_INTERRUPTED")
        assert EventType.WORKFLOW_INTERRUPTED.value == "workflow.interrupted"

    def test_create_workflow_interrupted_event(self):
        """Should create a valid WORKFLOW_INTERRUPTED event."""
        event = create_workflow_interrupted_event(
            run_id="test_run_123",
            reason="worker_lost",
            worker_id="worker_1",
            last_event_sequence=5,
            error="Worker process terminated unexpectedly",
            recovery_attempt=1,
            recoverable=True,
        )

        assert event.run_id == "test_run_123"
        assert event.type == EventType.WORKFLOW_INTERRUPTED
        assert event.data["reason"] == "worker_lost"
        assert event.data["worker_id"] == "worker_1"
        assert event.data["last_event_sequence"] == 5
        assert event.data["error"] == "Worker process terminated unexpectedly"
        assert event.data["recovery_attempt"] == 1
        assert event.data["recoverable"] is True

    def test_create_workflow_interrupted_event_minimal(self):
        """Should create event with minimal required fields."""
        event = create_workflow_interrupted_event(
            run_id="test_run_456",
            reason="timeout",
        )

        assert event.run_id == "test_run_456"
        assert event.type == EventType.WORKFLOW_INTERRUPTED
        assert event.data["reason"] == "timeout"
        assert event.data["worker_id"] is None
        assert event.data["last_event_sequence"] is None
        assert event.data["error"] is None
        assert event.data["recovery_attempt"] == 1
        assert event.data["recoverable"] is True

    def test_event_has_event_id(self):
        """Should generate a unique event_id."""
        event = create_workflow_interrupted_event(
            run_id="test_run",
            reason="signal",
        )

        assert event.event_id is not None
        assert event.event_id.startswith("evt_")

    def test_event_has_timestamp(self):
        """Should have a timestamp."""
        before = datetime.now(UTC)
        event = create_workflow_interrupted_event(
            run_id="test_run",
            reason="worker_lost",
        )
        after = datetime.now(UTC)

        assert event.timestamp is not None
        assert before <= event.timestamp <= after


class TestRunStatusInterrupted:
    """Tests for RunStatus.INTERRUPTED."""

    def test_status_exists(self):
        """INTERRUPTED should be defined in RunStatus."""
        assert hasattr(RunStatus, "INTERRUPTED")
        assert RunStatus.INTERRUPTED.value == "interrupted"

    def test_status_serialization(self):
        """Status should serialize and deserialize correctly."""
        status = RunStatus.INTERRUPTED
        serialized = status.value

        assert serialized == "interrupted"
        assert RunStatus(serialized) == RunStatus.INTERRUPTED


class TestWorkflowRunRecoveryFields:
    """Tests for WorkflowRun recovery tracking fields."""

    def test_default_values(self):
        """Should have correct default values for recovery fields."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
        )

        assert run.recovery_attempts == 0
        assert run.max_recovery_attempts == 3
        assert run.recover_on_worker_loss is True

    def test_custom_values(self):
        """Should accept custom recovery field values."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            recovery_attempts=2,
            max_recovery_attempts=5,
            recover_on_worker_loss=False,
        )

        assert run.recovery_attempts == 2
        assert run.max_recovery_attempts == 5
        assert run.recover_on_worker_loss is False

    def test_to_dict_includes_recovery_fields(self):
        """to_dict() should include recovery fields."""
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            recovery_attempts=1,
            max_recovery_attempts=3,
            recover_on_worker_loss=True,
        )

        data = run.to_dict()

        assert data["recovery_attempts"] == 1
        assert data["max_recovery_attempts"] == 3
        assert data["recover_on_worker_loss"] is True

    def test_from_dict_reads_recovery_fields(self):
        """from_dict() should read recovery fields."""
        data = {
            "run_id": "test_run",
            "workflow_name": "test_workflow",
            "status": "running",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "recovery_attempts": 2,
            "max_recovery_attempts": 4,
            "recover_on_worker_loss": False,
        }

        run = WorkflowRun.from_dict(data)

        assert run.recovery_attempts == 2
        assert run.max_recovery_attempts == 4
        assert run.recover_on_worker_loss is False

    def test_from_dict_defaults_missing_recovery_fields(self):
        """from_dict() should use defaults for missing recovery fields."""
        data = {
            "run_id": "test_run",
            "workflow_name": "test_workflow",
            "status": "running",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            # No recovery fields
        }

        run = WorkflowRun.from_dict(data)

        assert run.recovery_attempts == 0
        assert run.max_recovery_attempts == 3
        assert run.recover_on_worker_loss is True


class TestRecoveryConfig:
    """Tests for recovery configuration options."""

    def test_config_defaults(self):
        """Config should have correct default values."""
        config = PyWorkflowConfig()

        assert (
            config.default_recover_on_worker_loss is None
        )  # None = True for durable, False for transient
        assert config.default_max_recovery_attempts == 3

    def test_config_custom_values(self):
        """Config should accept custom values."""
        config = PyWorkflowConfig(
            default_recover_on_worker_loss=False,
            default_max_recovery_attempts=5,
        )

        assert config.default_recover_on_worker_loss is False
        assert config.default_max_recovery_attempts == 5


class TestReplayWorkflowInterrupted:
    """Tests for replay mechanism handling WORKFLOW_INTERRUPTED."""

    @pytest.mark.asyncio
    async def test_replay_workflow_interrupted_event(self):
        """Replayer should handle WORKFLOW_INTERRUPTED event without error."""
        from pyworkflow.context import LocalContext
        from pyworkflow.engine.replay import EventReplayer

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            event_log=[],
            durable=False,
        )

        event = Event(
            run_id="test_run",
            type=EventType.WORKFLOW_INTERRUPTED,
            data={
                "reason": "worker_lost",
                "recovery_attempt": 1,
                "last_event_sequence": 3,
            },
        )

        replayer = EventReplayer()
        await replayer._apply_event(ctx, event)

        # WORKFLOW_INTERRUPTED is informational, doesn't change state
        # Just verify it doesn't raise an exception

    @pytest.mark.asyncio
    async def test_replay_with_interrupted_event_in_sequence(self):
        """Replayer should handle WORKFLOW_INTERRUPTED in a sequence of events."""
        from pyworkflow.context import LocalContext
        from pyworkflow.engine.replay import EventReplayer
        from pyworkflow.serialization.encoder import serialize

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            event_log=[],
            durable=True,
        )

        events = [
            Event(
                run_id="test_run",
                type=EventType.WORKFLOW_STARTED,
                data={"workflow_name": "test_workflow", "args": "[]", "kwargs": "{}"},
                sequence=1,
            ),
            Event(
                run_id="test_run",
                type=EventType.STEP_COMPLETED,
                data={"step_id": "step_1", "result": serialize(42)},
                sequence=2,
            ),
            Event(
                run_id="test_run",
                type=EventType.WORKFLOW_INTERRUPTED,
                data={"reason": "worker_lost", "recovery_attempt": 1},
                sequence=3,
            ),
        ]

        replayer = EventReplayer()
        await replayer.replay(ctx, events)

        # Step result should be cached
        assert ctx.get_step_result("step_1") == 42


class TestStorageUpdateRecoveryAttempts:
    """Tests for storage backend update_run_recovery_attempts method."""

    @pytest.mark.asyncio
    async def test_memory_storage_update_recovery_attempts(self):
        """InMemoryStorageBackend should update recovery_attempts."""
        from pyworkflow.storage.memory import InMemoryStorageBackend

        storage = InMemoryStorageBackend()

        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            recovery_attempts=0,
        )
        await storage.create_run(run)

        await storage.update_run_recovery_attempts("test_run", 2)

        updated_run = await storage.get_run("test_run")
        assert updated_run.recovery_attempts == 2

    @pytest.mark.asyncio
    async def test_file_storage_update_recovery_attempts(self, tmp_path):
        """FileStorageBackend should update recovery_attempts."""
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend(base_path=str(tmp_path))

        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            recovery_attempts=0,
        )
        await storage.create_run(run)

        await storage.update_run_recovery_attempts("test_run", 3)

        updated_run = await storage.get_run("test_run")
        assert updated_run.recovery_attempts == 3
