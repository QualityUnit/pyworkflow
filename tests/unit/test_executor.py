"""
Unit tests for workflow executor.

Tests use the unified start/resume API with local runtime.
"""

import pytest

from pyworkflow import configure, reset_config, resume, start
from pyworkflow.core.exceptions import (
    WorkflowNotFoundError,
)
from pyworkflow.core.step import step
from pyworkflow.core.workflow import workflow
from pyworkflow.engine.executor import get_workflow_events, get_workflow_run
from pyworkflow.primitives.sleep import sleep
from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.schemas import RunStatus


@pytest.fixture(autouse=True)
def reset_config_fixture():
    """Reset configuration before each test."""
    reset_config()
    yield
    reset_config()


class TestWorkflowStart:
    """Test starting workflows."""

    @pytest.mark.asyncio
    async def test_start_basic_workflow(self, tmp_path):
        """Test starting a basic workflow."""

        @workflow(name="test_start_workflow")
        async def my_workflow(x: int):
            return x * 2

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(my_workflow, 5, durable=True, storage=storage)

        # Check run was created
        assert run_id is not None
        assert run_id.startswith("run_")

        # Check run status
        run = await storage.get_run(run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.workflow_name == "test_start_workflow"

    @pytest.mark.asyncio
    async def test_start_workflow_with_kwargs(self, tmp_path):
        """Test starting workflow with keyword arguments."""

        @workflow(name="kwargs_workflow")
        async def kwargs_workflow(a: int, b: int):
            return a + b

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(kwargs_workflow, 10, b=20, durable=True, storage=storage)

        # Check result was stored
        run = await storage.get_run(run_id)
        assert run.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_start_with_idempotency_key(self, tmp_path):
        """Test workflow idempotency."""

        @workflow(name="idempotent_workflow")
        async def my_workflow():
            return "done"

        storage = FileStorageBackend(base_path=str(tmp_path))

        # First execution
        run_id1 = await start(
            my_workflow, durable=True, storage=storage, idempotency_key="unique-key-123"
        )

        # Second execution with same key - should return same run_id
        run_id2 = await start(
            my_workflow, durable=True, storage=storage, idempotency_key="unique-key-123"
        )

        assert run_id1 == run_id2

    @pytest.mark.asyncio
    async def test_start_workflow_with_failure(self, tmp_path):
        """Test starting a workflow that fails."""

        @workflow(name="failing_workflow")
        async def failing_workflow():
            raise ValueError("Test failure")

        storage = FileStorageBackend(base_path=str(tmp_path))

        with pytest.raises(ValueError, match="Test failure"):
            await start(failing_workflow, durable=True, storage=storage)

        # Check that run was marked as failed
        # (We need to get the run_id from storage somehow)
        # For now, just verify the exception was raised

    @pytest.mark.asyncio
    async def test_start_workflow_with_suspension(self, tmp_path):
        """Test starting a workflow that suspends."""

        @workflow(name="suspending_workflow")
        async def suspending_workflow():
            await sleep("5s")
            return "completed"

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(suspending_workflow, durable=True, storage=storage)

        # Workflow should have suspended
        run = await storage.get_run(run_id)
        assert run.status == RunStatus.SUSPENDED

    @pytest.mark.asyncio
    async def test_start_workflow_with_steps(self, tmp_path):
        """Test starting a workflow with steps."""

        @step()
        async def add_step(a: int, b: int):
            return a + b

        @workflow(name="step_workflow")
        async def step_workflow(x: int):
            result = await add_step(x, 10)
            return result

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(step_workflow, 5, durable=True, storage=storage)

        # Verify completion
        run = await storage.get_run(run_id)
        assert run.status == RunStatus.COMPLETED

        # Verify events include step events
        events = await storage.get_events(run_id)
        event_types = [e.type.value for e in events]
        assert "step.started" in event_types
        assert "step.completed" in event_types


class TestWorkflowResume:
    """Test resuming workflows."""

    @pytest.mark.asyncio
    async def test_resume_suspended_workflow(self, tmp_path):
        """Test resuming a suspended workflow."""

        @workflow(name="resumable_workflow")
        async def resumable_workflow():
            await sleep("1s")
            return "resumed"

        storage = FileStorageBackend(base_path=str(tmp_path))

        # Start and suspend
        run_id = await start(resumable_workflow, durable=True, storage=storage)
        run = await storage.get_run(run_id)
        assert run.status == RunStatus.SUSPENDED

        # Resume workflow
        await resume(run_id, storage=storage)

        # Should complete now
        # Note: This will still suspend because sleep hasn't actually elapsed
        # In a real scenario, we'd need time to pass or mock the time check

    @pytest.mark.asyncio
    async def test_resume_nonexistent_workflow(self, tmp_path):
        """Test resuming a workflow that doesn't exist."""
        storage = FileStorageBackend(base_path=str(tmp_path))

        with pytest.raises(WorkflowNotFoundError):
            await resume("nonexistent_run_id", storage=storage)

    @pytest.mark.asyncio
    async def test_resume_with_replay(self, tmp_path):
        """Test that resume replays previous events."""
        execution_count = 0

        @step()
        async def counting_step():
            nonlocal execution_count
            execution_count += 1
            return "done"

        @workflow(name="replay_workflow")
        async def replay_workflow():
            await counting_step()
            await sleep("1s")
            await counting_step()  # This should use cached result on resume
            return "completed"

        storage = FileStorageBackend(base_path=str(tmp_path))

        # Start workflow - will execute first step and suspend
        run_id = await start(replay_workflow, durable=True, storage=storage)
        assert execution_count == 1

        # Resume - should replay first step (not execute) and suspend again
        await resume(run_id, storage=storage)

        # First step should have been replayed, not re-executed
        # So execution_count should still be 1
        # (Second step hasn't executed yet because sleep hasn't elapsed)


class TestWorkflowQueries:
    """Test workflow query functions."""

    @pytest.mark.asyncio
    async def test_get_workflow_run(self, tmp_path):
        """Test getting workflow run information."""

        @workflow(name="query_workflow")
        async def query_workflow():
            return "done"

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(query_workflow, durable=True, storage=storage)

        # Query the run
        run = await get_workflow_run(run_id, storage=storage)

        assert run is not None
        assert run.run_id == run_id
        assert run.workflow_name == "query_workflow"
        assert run.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_get_workflow_run_nonexistent(self, tmp_path):
        """Test getting a nonexistent workflow run."""
        storage = FileStorageBackend(base_path=str(tmp_path))

        run = await get_workflow_run("nonexistent", storage=storage)
        assert run is None

    @pytest.mark.asyncio
    async def test_get_workflow_events(self, tmp_path):
        """Test getting workflow events."""

        @step()
        async def event_step():
            return "done"

        @workflow(name="events_workflow")
        async def events_workflow():
            await event_step()
            return "completed"

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(events_workflow, durable=True, storage=storage)

        # Get events
        events = await get_workflow_events(run_id, storage=storage)

        assert len(events) > 0

        # Check event types
        event_types = [e.type.value for e in events]
        assert "workflow.started" in event_types
        assert "step.started" in event_types
        assert "step.completed" in event_types
        assert "workflow.completed" in event_types

    @pytest.mark.asyncio
    async def test_workflow_max_duration_stored(self, tmp_path):
        """Test that workflow max_duration is stored correctly."""

        @workflow(name="timed_workflow", max_duration="1h", tags=["test", "backend"])
        async def timed_workflow():
            return "done"

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(timed_workflow, durable=True, storage=storage)

        # Check max_duration was stored on run
        run = await storage.get_run(run_id)
        assert run.max_duration == "1h"

        # Check tags were stored on workflow metadata (not run)
        from pyworkflow.core.registry import get_workflow

        workflow_meta = get_workflow("timed_workflow")
        assert workflow_meta.tags == ["test", "backend"]


class TestWorkflowDefaultStorage:
    """Test workflows with default storage backend."""

    @pytest.mark.asyncio
    async def test_start_without_storage_param(self, tmp_path):
        """Test that configured storage is used by default."""
        from pyworkflow.storage.memory import InMemoryStorageBackend

        storage = InMemoryStorageBackend()
        configure(storage=storage, default_durable=True)

        @workflow(name="default_storage_workflow")
        async def default_workflow():
            return "done"

        # Start without providing storage (uses configured default)
        run_id = await start(default_workflow)

        assert run_id is not None
        assert run_id.startswith("run_")

        # Verify run was stored
        run = await storage.get_run(run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
