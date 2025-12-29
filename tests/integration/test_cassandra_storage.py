"""
Integration tests for Cassandra storage backend.

These tests require Cassandra to be running on localhost:9042.
To start Cassandra:
    docker run -p 9042:9042 cassandra:latest

Tests will be skipped if Cassandra is not available.
"""

import socket
import uuid
from datetime import UTC, datetime, timedelta

import pytest

# Skip all tests if dependencies are not installed
pytest.importorskip("cassandra")

from pyworkflow.engine.events import Event, EventType
from pyworkflow.storage.cassandra import CassandraStorageBackend
from pyworkflow.storage.schemas import (
    Hook,
    HookStatus,
    RunStatus,
    Schedule,
    ScheduleSpec,
    ScheduleStatus,
    StepExecution,
    StepStatus,
    WorkflowRun,
)


def is_cassandra_available(host: str = "localhost", port: int = 9042) -> bool:
    """Check if Cassandra is available."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


# Skip all tests if Cassandra is not running
pytestmark = pytest.mark.skipif(
    not is_cassandra_available(),
    reason="Cassandra is not available at localhost:9042. "
    "Start with: docker run -p 9042:9042 cassandra:latest",
)


@pytest.fixture
async def cassandra_storage():
    """Create a Cassandra storage backend connected to local Cassandra."""
    # Use unique keyspace per test to avoid conflicts
    keyspace = f"test_pyworkflow_{uuid.uuid4().hex[:8]}"

    backend = CassandraStorageBackend(
        contact_points=["localhost"],
        port=9042,
        keyspace=keyspace,
        replication_factor=1,  # Single node for testing
    )
    await backend.connect()
    yield backend

    # Cleanup: drop the test keyspace
    try:
        if backend._session:
            backend._session.execute(f"DROP KEYSPACE IF EXISTS {keyspace}")
    except Exception:
        pass

    await backend.disconnect()


class TestWorkflowRunCRUD:
    """Test workflow run CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_and_get_run(self, cassandra_storage):
        """Test creating and retrieving a workflow run."""
        now = datetime.now(UTC)
        run = WorkflowRun(
            run_id="test_run_001",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs='{"key": "value"}',
        )

        await cassandra_storage.create_run(run)

        retrieved = await cassandra_storage.get_run("test_run_001")
        assert retrieved is not None
        assert retrieved.run_id == "test_run_001"
        assert retrieved.workflow_name == "test_workflow"
        assert retrieved.status == RunStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_run_not_found(self, cassandra_storage):
        """Test getting a non-existent run."""
        retrieved = await cassandra_storage.get_run("nonexistent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_update_run_status(self, cassandra_storage):
        """Test updating run status."""
        now = datetime.now(UTC)
        run = WorkflowRun(
            run_id="status_update_test",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        await cassandra_storage.update_run_status(
            run_id="status_update_test",
            status=RunStatus.RUNNING,
        )

        retrieved = await cassandra_storage.get_run("status_update_test")
        assert retrieved.status == RunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_update_run_status_with_result(self, cassandra_storage):
        """Test updating run status with result."""
        now = datetime.now(UTC)
        run = WorkflowRun(
            run_id="result_test",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        await cassandra_storage.update_run_status(
            run_id="result_test",
            status=RunStatus.COMPLETED,
            result='{"output": "success"}',
        )

        retrieved = await cassandra_storage.get_run("result_test")
        assert retrieved.status == RunStatus.COMPLETED
        assert retrieved.result == '{"output": "success"}'

    @pytest.mark.asyncio
    async def test_get_run_by_idempotency_key(self, cassandra_storage):
        """Test retrieving run by idempotency key."""
        now = datetime.now(UTC)
        run = WorkflowRun(
            run_id="idempotent_run",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
            idempotency_key="unique_key_123",
        )
        await cassandra_storage.create_run(run)

        retrieved = await cassandra_storage.get_run_by_idempotency_key("unique_key_123")
        assert retrieved is not None
        assert retrieved.run_id == "idempotent_run"

    @pytest.mark.asyncio
    async def test_get_run_by_idempotency_key_not_found(self, cassandra_storage):
        """Test idempotency key lookup when not found."""
        retrieved = await cassandra_storage.get_run_by_idempotency_key("nonexistent_key")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_update_recovery_attempts(self, cassandra_storage):
        """Test updating recovery attempts counter."""
        now = datetime.now(UTC)
        run = WorkflowRun(
            run_id="recovery_test",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
            recovery_attempts=0,
        )
        await cassandra_storage.create_run(run)

        await cassandra_storage.update_run_recovery_attempts("recovery_test", 2)

        retrieved = await cassandra_storage.get_run("recovery_test")
        assert retrieved.recovery_attempts == 2

    @pytest.mark.asyncio
    async def test_update_run_context(self, cassandra_storage):
        """Test updating run context."""
        now = datetime.now(UTC)
        run = WorkflowRun(
            run_id="context_test",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        new_context = {"step_results": {"step_1": "done"}}
        await cassandra_storage.update_run_context("context_test", new_context)

        retrieved_context = await cassandra_storage.get_run_context("context_test")
        assert retrieved_context == new_context

    @pytest.mark.asyncio
    async def test_list_runs_with_status_filter(self, cassandra_storage):
        """Test listing runs filtered by status."""
        now = datetime.now(UTC)

        # Create runs with different statuses
        for i, status in enumerate([RunStatus.PENDING, RunStatus.RUNNING, RunStatus.COMPLETED]):
            run = WorkflowRun(
                run_id=f"status_filter_{i}",
                workflow_name="test_workflow",
                status=status,
                created_at=now + timedelta(seconds=i),
                updated_at=now + timedelta(seconds=i),
                input_args="[]",
                input_kwargs="{}",
            )
            await cassandra_storage.create_run(run)

        runs, _ = await cassandra_storage.list_runs(status=RunStatus.PENDING)

        assert len(runs) >= 1
        assert all(r.status == RunStatus.PENDING for r in runs)


class TestEventOperations:
    """Test event log operations."""

    @pytest.mark.asyncio
    async def test_record_and_get_events(self, cassandra_storage):
        """Test recording and retrieving events."""
        now = datetime.now(UTC)

        # First create a run
        run = WorkflowRun(
            run_id="event_test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        # Record events
        for i in range(3):
            event = Event(
                event_id=f"evt_{i}",
                run_id="event_test_run",
                type=EventType.STEP_COMPLETED,
                timestamp=now + timedelta(seconds=i),
                data={"step_id": f"step_{i}", "result": f"result_{i}"},
            )
            await cassandra_storage.record_event(event)

        # Retrieve events
        events = await cassandra_storage.get_events("event_test_run")

        assert len(events) == 3
        # Events should be ordered by TIMEUUID (time-based)
        for i, event in enumerate(events):
            assert event.sequence == i

    @pytest.mark.asyncio
    async def test_get_events_with_type_filter(self, cassandra_storage):
        """Test retrieving events filtered by type."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="event_filter_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        # Record different event types
        events_to_create = [
            (EventType.WORKFLOW_STARTED, {}),
            (EventType.STEP_STARTED, {"step_id": "step_1"}),
            (EventType.STEP_COMPLETED, {"step_id": "step_1", "result": "ok"}),
            (EventType.WORKFLOW_COMPLETED, {"result": "done"}),
        ]

        for i, (event_type, data) in enumerate(events_to_create):
            event = Event(
                event_id=f"evt_{i}",
                run_id="event_filter_run",
                type=event_type,
                timestamp=now + timedelta(seconds=i),
                data=data,
            )
            await cassandra_storage.record_event(event)

        # Filter by type
        step_events = await cassandra_storage.get_events(
            "event_filter_run",
            event_types=["step.completed"],
        )

        assert len(step_events) == 1
        assert step_events[0].type == EventType.STEP_COMPLETED

    @pytest.mark.asyncio
    async def test_get_latest_event(self, cassandra_storage):
        """Test getting the latest event."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="latest_event_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        # Record multiple events
        for i in range(5):
            event = Event(
                event_id=f"evt_{i}",
                run_id="latest_event_run",
                type=EventType.STEP_COMPLETED,
                timestamp=now + timedelta(seconds=i),
                data={"index": i},
            )
            await cassandra_storage.record_event(event)

        latest = await cassandra_storage.get_latest_event("latest_event_run")

        assert latest is not None
        assert latest.sequence == 4  # 0-indexed


class TestStepOperations:
    """Test step execution operations."""

    @pytest.mark.asyncio
    async def test_create_and_get_step(self, cassandra_storage):
        """Test creating and retrieving a step."""
        now = datetime.now(UTC)

        # First create a run
        run = WorkflowRun(
            run_id="step_test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        step = StepExecution(
            step_id="step_001",
            run_id="step_test_run",
            step_name="process_data",
            status=StepStatus.RUNNING,
            created_at=now,
            started_at=now,
            input_args="[]",
            input_kwargs='{"data": "test"}',
            attempt=1,
        )
        await cassandra_storage.create_step(step)

        retrieved = await cassandra_storage.get_step("step_001")
        assert retrieved is not None
        assert retrieved.step_id == "step_001"
        assert retrieved.step_name == "process_data"
        assert retrieved.status == StepStatus.RUNNING

    @pytest.mark.asyncio
    async def test_update_step_status(self, cassandra_storage):
        """Test updating step status."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="step_update_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        step = StepExecution(
            step_id="step_update_001",
            run_id="step_update_run",
            step_name="test_step",
            status=StepStatus.RUNNING,
            created_at=now,
            input_args="[]",
            input_kwargs="{}",
            attempt=1,
        )
        await cassandra_storage.create_step(step)

        await cassandra_storage.update_step_status(
            step_id="step_update_001",
            status="completed",
            result='{"output": "success"}',
        )

        retrieved = await cassandra_storage.get_step("step_update_001")
        assert retrieved.status == StepStatus.COMPLETED
        assert retrieved.result == '{"output": "success"}'

    @pytest.mark.asyncio
    async def test_list_steps(self, cassandra_storage):
        """Test listing steps for a run."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="list_steps_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        # Create multiple steps
        for i in range(3):
            step = StepExecution(
                step_id=f"list_step_{i}",
                run_id="list_steps_run",
                step_name=f"step_{i}",
                status=StepStatus.COMPLETED,
                created_at=now + timedelta(seconds=i),
                input_args="[]",
                input_kwargs="{}",
                attempt=1,
            )
            await cassandra_storage.create_step(step)

        steps = await cassandra_storage.list_steps("list_steps_run")

        assert len(steps) == 3


class TestHookOperations:
    """Test webhook/hook operations."""

    @pytest.mark.asyncio
    async def test_create_and_get_hook(self, cassandra_storage):
        """Test creating and retrieving a hook."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="hook_test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        hook = Hook(
            hook_id="hook_001",
            run_id="hook_test_run",
            token="token_abc123",
            status=HookStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        await cassandra_storage.create_hook(hook)

        retrieved = await cassandra_storage.get_hook("hook_001")
        assert retrieved is not None
        assert retrieved.hook_id == "hook_001"
        assert retrieved.token == "token_abc123"
        assert retrieved.status == HookStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_hook_by_token(self, cassandra_storage):
        """Test retrieving hook by token."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="hook_token_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        hook = Hook(
            hook_id="hook_token_001",
            run_id="hook_token_run",
            token="unique_token_xyz",
            status=HookStatus.PENDING,
            created_at=now,
        )
        await cassandra_storage.create_hook(hook)

        retrieved = await cassandra_storage.get_hook_by_token("unique_token_xyz")
        assert retrieved is not None
        assert retrieved.hook_id == "hook_token_001"

    @pytest.mark.asyncio
    async def test_update_hook_status(self, cassandra_storage):
        """Test updating hook status with payload."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="hook_update_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        hook = Hook(
            hook_id="hook_update_001",
            run_id="hook_update_run",
            token="update_token",
            status=HookStatus.PENDING,
            created_at=now,
        )
        await cassandra_storage.create_hook(hook)

        await cassandra_storage.update_hook_status(
            hook_id="hook_update_001",
            status=HookStatus.RECEIVED,
            payload='{"data": "webhook_payload"}',
        )

        retrieved = await cassandra_storage.get_hook("hook_update_001")
        assert retrieved.status == HookStatus.RECEIVED
        assert retrieved.payload == '{"data": "webhook_payload"}'

    @pytest.mark.asyncio
    async def test_list_hooks(self, cassandra_storage):
        """Test listing hooks for a run."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="list_hooks_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        # Create multiple hooks
        for i in range(3):
            hook = Hook(
                hook_id=f"list_hook_{i}",
                run_id="list_hooks_run",
                token=f"token_{i}",
                status=HookStatus.PENDING,
                created_at=now + timedelta(seconds=i),
            )
            await cassandra_storage.create_hook(hook)

        hooks = await cassandra_storage.list_hooks(run_id="list_hooks_run")

        assert len(hooks) == 3


class TestCancellationOperations:
    """Test cancellation flag operations."""

    @pytest.mark.asyncio
    async def test_set_and_check_cancellation_flag(self, cassandra_storage):
        """Test setting and checking cancellation flag."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="cancel_test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        # Initially no cancellation
        assert await cassandra_storage.check_cancellation_flag("cancel_test_run") is False

        # Set cancellation
        await cassandra_storage.set_cancellation_flag("cancel_test_run")

        # Now should be cancelled
        assert await cassandra_storage.check_cancellation_flag("cancel_test_run") is True

    @pytest.mark.asyncio
    async def test_clear_cancellation_flag(self, cassandra_storage):
        """Test clearing cancellation flag."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="clear_cancel_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        await cassandra_storage.set_cancellation_flag("clear_cancel_run")
        assert await cassandra_storage.check_cancellation_flag("clear_cancel_run") is True

        await cassandra_storage.clear_cancellation_flag("clear_cancel_run")
        assert await cassandra_storage.check_cancellation_flag("clear_cancel_run") is False


class TestContinueAsNewOperations:
    """Test continue-as-new chain operations."""

    @pytest.mark.asyncio
    async def test_update_run_continuation(self, cassandra_storage):
        """Test updating run continuation link."""
        now = datetime.now(UTC)

        # Create original run
        run1 = WorkflowRun(
            run_id="chain_run_1",
            workflow_name="test_workflow",
            status=RunStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run1)

        # Create continuation run
        run2 = WorkflowRun(
            run_id="chain_run_2",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now + timedelta(seconds=1),
            updated_at=now + timedelta(seconds=1),
            input_args="[]",
            input_kwargs="{}",
            continued_from_run_id="chain_run_1",
        )
        await cassandra_storage.create_run(run2)

        # Link the runs
        await cassandra_storage.update_run_continuation("chain_run_1", "chain_run_2")

        retrieved = await cassandra_storage.get_run("chain_run_1")
        assert retrieved.continued_to_run_id == "chain_run_2"

    @pytest.mark.asyncio
    async def test_get_workflow_chain(self, cassandra_storage):
        """Test getting workflow chain."""
        now = datetime.now(UTC)

        # Create a chain of 3 runs
        run1 = WorkflowRun(
            run_id="chain_1",
            workflow_name="test_workflow",
            status=RunStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
            continued_to_run_id="chain_2",
        )
        await cassandra_storage.create_run(run1)

        run2 = WorkflowRun(
            run_id="chain_2",
            workflow_name="test_workflow",
            status=RunStatus.COMPLETED,
            created_at=now + timedelta(seconds=1),
            updated_at=now + timedelta(seconds=1),
            input_args="[]",
            input_kwargs="{}",
            continued_from_run_id="chain_1",
            continued_to_run_id="chain_3",
        )
        await cassandra_storage.create_run(run2)

        run3 = WorkflowRun(
            run_id="chain_3",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now + timedelta(seconds=2),
            updated_at=now + timedelta(seconds=2),
            input_args="[]",
            input_kwargs="{}",
            continued_from_run_id="chain_2",
        )
        await cassandra_storage.create_run(run3)

        # Get chain from middle run
        chain = await cassandra_storage.get_workflow_chain("chain_2")

        assert len(chain) == 3
        assert chain[0].run_id == "chain_1"
        assert chain[1].run_id == "chain_2"
        assert chain[2].run_id == "chain_3"


class TestChildWorkflowOperations:
    """Test child workflow operations."""

    @pytest.mark.asyncio
    async def test_get_children(self, cassandra_storage):
        """Test getting child workflows."""
        now = datetime.now(UTC)

        # Create parent run
        parent = WorkflowRun(
            run_id="parent_run",
            workflow_name="parent_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
            nesting_depth=0,
        )
        await cassandra_storage.create_run(parent)

        # Create child runs
        for i in range(3):
            child = WorkflowRun(
                run_id=f"child_run_{i}",
                workflow_name="child_workflow",
                status=RunStatus.COMPLETED if i < 2 else RunStatus.RUNNING,
                created_at=now + timedelta(seconds=i),
                updated_at=now + timedelta(seconds=i),
                input_args="[]",
                input_kwargs="{}",
                parent_run_id="parent_run",
                nesting_depth=1,
            )
            await cassandra_storage.create_run(child)

        children = await cassandra_storage.get_children("parent_run")

        assert len(children) == 3

    @pytest.mark.asyncio
    async def test_get_children_with_status_filter(self, cassandra_storage):
        """Test getting children filtered by status."""
        now = datetime.now(UTC)

        parent = WorkflowRun(
            run_id="filter_parent",
            workflow_name="parent_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(parent)

        # Create child runs with different statuses
        for i, status in enumerate([RunStatus.COMPLETED, RunStatus.COMPLETED, RunStatus.RUNNING]):
            child = WorkflowRun(
                run_id=f"filter_child_{i}",
                workflow_name="child_workflow",
                status=status,
                created_at=now + timedelta(seconds=i),
                updated_at=now + timedelta(seconds=i),
                input_args="[]",
                input_kwargs="{}",
                parent_run_id="filter_parent",
                nesting_depth=1,
            )
            await cassandra_storage.create_run(child)

        completed = await cassandra_storage.get_children(
            "filter_parent", status=RunStatus.COMPLETED
        )

        assert len(completed) == 2

    @pytest.mark.asyncio
    async def test_get_parent(self, cassandra_storage):
        """Test getting parent workflow."""
        now = datetime.now(UTC)

        parent = WorkflowRun(
            run_id="the_parent",
            workflow_name="parent_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(parent)

        child = WorkflowRun(
            run_id="the_child",
            workflow_name="child_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
            parent_run_id="the_parent",
            nesting_depth=1,
        )
        await cassandra_storage.create_run(child)

        retrieved_parent = await cassandra_storage.get_parent("the_child")

        assert retrieved_parent is not None
        assert retrieved_parent.run_id == "the_parent"

    @pytest.mark.asyncio
    async def test_get_nesting_depth(self, cassandra_storage):
        """Test getting nesting depth."""
        now = datetime.now(UTC)

        run = WorkflowRun(
            run_id="depth_test",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
            nesting_depth=2,
        )
        await cassandra_storage.create_run(run)

        depth = await cassandra_storage.get_nesting_depth("depth_test")

        assert depth == 2


class TestScheduleOperations:
    """Test schedule CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_and_get_schedule(self, cassandra_storage):
        """Test creating and retrieving a schedule."""
        now = datetime.now(UTC)
        spec = ScheduleSpec(cron="0 9 * * *")
        schedule = Schedule(
            schedule_id="schedule_001",
            workflow_name="scheduled_workflow",
            spec=spec,
            status=ScheduleStatus.ACTIVE,
            created_at=now,
        )

        await cassandra_storage.create_schedule(schedule)

        retrieved = await cassandra_storage.get_schedule("schedule_001")
        assert retrieved is not None
        assert retrieved.schedule_id == "schedule_001"
        assert retrieved.workflow_name == "scheduled_workflow"
        assert retrieved.spec.cron == "0 9 * * *"
        assert retrieved.status == ScheduleStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_delete_schedule(self, cassandra_storage):
        """Test deleting (soft delete) a schedule."""
        now = datetime.now(UTC)
        spec = ScheduleSpec(interval="5m")
        schedule = Schedule(
            schedule_id="delete_schedule",
            workflow_name="test_workflow",
            spec=spec,
            status=ScheduleStatus.ACTIVE,
            created_at=now,
        )
        await cassandra_storage.create_schedule(schedule)

        await cassandra_storage.delete_schedule("delete_schedule")

        retrieved = await cassandra_storage.get_schedule("delete_schedule")
        assert retrieved.status == ScheduleStatus.DELETED

    @pytest.mark.asyncio
    async def test_get_due_schedules(self, cassandra_storage):
        """Test getting due schedules with bucket walking."""
        now = datetime.now(UTC)
        past = now - timedelta(minutes=5)
        future = now + timedelta(minutes=5)

        # Create schedules with different next_run_times
        for i, (next_run, status) in enumerate(
            [
                (past, ScheduleStatus.ACTIVE),
                (past, ScheduleStatus.ACTIVE),
                (future, ScheduleStatus.ACTIVE),
                (past, ScheduleStatus.PAUSED),  # Paused should not be returned
            ]
        ):
            schedule = Schedule(
                schedule_id=f"due_sched_{i}",
                workflow_name="test_workflow",
                spec=ScheduleSpec(cron="0 9 * * *"),
                status=status,
                next_run_time=next_run,
                created_at=now,
            )
            await cassandra_storage.create_schedule(schedule)

        due = await cassandra_storage.get_due_schedules(now)

        # Only 2 active schedules with past next_run_time
        assert len(due) == 2

    @pytest.mark.asyncio
    async def test_add_and_remove_running_run(self, cassandra_storage):
        """Test adding and removing running run IDs."""
        now = datetime.now(UTC)
        schedule = Schedule(
            schedule_id="running_sched",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            status=ScheduleStatus.ACTIVE,
            created_at=now,
        )
        await cassandra_storage.create_schedule(schedule)

        # Add running runs
        await cassandra_storage.add_running_run("running_sched", "run_1")
        await cassandra_storage.add_running_run("running_sched", "run_2")

        retrieved = await cassandra_storage.get_schedule("running_sched")
        assert "run_1" in retrieved.running_run_ids
        assert "run_2" in retrieved.running_run_ids
        assert len(retrieved.running_run_ids) == 2

        # Remove a run
        await cassandra_storage.remove_running_run("running_sched", "run_1")

        retrieved = await cassandra_storage.get_schedule("running_sched")
        assert "run_1" not in retrieved.running_run_ids
        assert "run_2" in retrieved.running_run_ids


class TestLifecycleMethods:
    """Test lifecycle methods (connect, disconnect, health_check)."""

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self, cassandra_storage):
        """Test health check returns True for healthy backend."""
        result = await cassandra_storage.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_disconnect_and_reconnect(self, cassandra_storage):
        """Test that disconnect works and reconnect is possible."""
        # First verify we can create a run
        now = datetime.now(UTC)
        run = WorkflowRun(
            run_id="lifecycle_test_run",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )
        await cassandra_storage.create_run(run)

        # Verify it was created
        retrieved = await cassandra_storage.get_run("lifecycle_test_run")
        assert retrieved is not None

        # Store keyspace for reconnect
        keyspace = cassandra_storage.keyspace

        # Disconnect
        await cassandra_storage.disconnect()
        assert cassandra_storage._initialized is False

        # Reconnect
        cassandra_storage.keyspace = keyspace
        await cassandra_storage.connect()
        assert cassandra_storage._initialized is True

        # Verify we can still perform operations after reconnecting
        retrieved = await cassandra_storage.get_run("lifecycle_test_run")
        assert retrieved is not None
        assert retrieved.run_id == "lifecycle_test_run"

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_disconnected(self):
        """Test health check returns False when not connected."""
        backend = CassandraStorageBackend()
        # Don't connect - should return False
        result = await backend.health_check()
        assert result is False
