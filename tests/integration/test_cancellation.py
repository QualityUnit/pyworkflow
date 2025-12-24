"""
Integration tests for cancellation feature.

Tests cover:
- cancel_workflow() function
- Cancellation during step execution
- Cancellation during sleep
- Cancellation during hook wait
- Shield prevents cancellation
- Workflow catches CancellationError for cleanup
"""

import asyncio

import pytest

from pyworkflow import (
    CancellationError,
    RunStatus,
    cancel_workflow,
    shield,
    step,
)
from pyworkflow.engine.events import EventType
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import WorkflowRun


class TestCancelWorkflowFunction:
    """Test cancel_workflow() function."""

    @pytest.mark.asyncio
    async def test_cancel_running_workflow(self):
        """Test cancelling a running workflow."""
        storage = InMemoryStorageBackend()

        # Create a workflow run record
        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
        )
        await storage.create_run(run)

        # Cancel the workflow
        result = await cancel_workflow(
            run_id="run_123",
            reason="User cancelled",
            storage=storage,
        )

        assert result is True

        # Check cancellation flag was set
        assert await storage.check_cancellation_flag("run_123") is True

        # Check cancellation event was recorded
        events = await storage.get_events("run_123")
        cancellation_events = [e for e in events if e.type == EventType.CANCELLATION_REQUESTED]
        assert len(cancellation_events) == 1
        assert cancellation_events[0].data["reason"] == "User cancelled"

    @pytest.mark.asyncio
    async def test_cancel_suspended_workflow(self):
        """Test cancelling a suspended workflow marks it as cancelled."""
        storage = InMemoryStorageBackend()

        # Create a suspended workflow
        run = WorkflowRun(
            run_id="run_456",
            workflow_name="test_workflow",
            status=RunStatus.SUSPENDED,
        )
        await storage.create_run(run)

        # Cancel the workflow
        result = await cancel_workflow(
            run_id="run_456",
            storage=storage,
        )

        assert result is True

        # Suspended workflows should be marked as cancelled immediately
        updated_run = await storage.get_run("run_456")
        assert updated_run.status == RunStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_workflow_returns_false(self):
        """Test cancelling an already completed workflow returns False."""
        storage = InMemoryStorageBackend()

        # Create a completed workflow
        run = WorkflowRun(
            run_id="run_789",
            workflow_name="test_workflow",
            status=RunStatus.COMPLETED,
        )
        await storage.create_run(run)

        # Try to cancel
        result = await cancel_workflow(
            run_id="run_789",
            storage=storage,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_failed_workflow_returns_false(self):
        """Test cancelling an already failed workflow returns False."""
        storage = InMemoryStorageBackend()

        # Create a failed workflow
        run = WorkflowRun(
            run_id="run_abc",
            workflow_name="test_workflow",
            status=RunStatus.FAILED,
        )
        await storage.create_run(run)

        # Try to cancel
        result = await cancel_workflow(
            run_id="run_abc",
            storage=storage,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_workflow_returns_false(self):
        """Test cancelling an already cancelled workflow returns False."""
        storage = InMemoryStorageBackend()

        # Create a cancelled workflow
        run = WorkflowRun(
            run_id="run_def",
            workflow_name="test_workflow",
            status=RunStatus.CANCELLED,
        )
        await storage.create_run(run)

        # Try to cancel again
        result = await cancel_workflow(
            run_id="run_def",
            storage=storage,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_workflow(self):
        """Test cancelling a non-existent workflow raises error."""
        from pyworkflow import WorkflowNotFoundError

        storage = InMemoryStorageBackend()

        with pytest.raises(WorkflowNotFoundError):
            await cancel_workflow(
                run_id="nonexistent",
                storage=storage,
            )


class TestCancellationCheckPoints:
    """Test cancellation at various check points."""

    @pytest.mark.asyncio
    async def test_step_checks_cancellation(self):
        """Test that step execution checks for cancellation."""
        from pyworkflow.context import LocalContext, reset_context, set_context

        @step()
        async def my_step():
            return "result"

        # Create context with cancellation requested
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.request_cancellation(reason="Test")
        token = set_context(ctx)

        try:
            with pytest.raises(CancellationError):
                await my_step()
        finally:
            reset_context(token)


class TestShieldIntegration:
    """Test shield() integration with workflow execution."""

    @pytest.mark.asyncio
    async def test_shield_allows_cleanup(self):
        """Test shield() allows cleanup operations to complete."""
        from pyworkflow.context import LocalContext, reset_context, set_context

        cleanup_completed = False

        async def cleanup():
            nonlocal cleanup_completed
            await asyncio.sleep(0.01)  # Simulate cleanup work
            cleanup_completed = True

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.request_cancellation()
        token = set_context(ctx)

        try:
            async with shield():
                await cleanup()

            assert cleanup_completed is True
        finally:
            reset_context(token)


class TestFileCancellationFlags:
    """Test file storage backend cancellation flags."""

    @pytest.mark.asyncio
    async def test_file_storage_cancellation_flags(self, tmp_path):
        """Test FileStorageBackend cancellation flag methods."""
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend(base_path=str(tmp_path / "workflow_data"))

        # Initially not set
        assert await storage.check_cancellation_flag("run_123") is False

        # Set the flag
        await storage.set_cancellation_flag("run_123")
        assert await storage.check_cancellation_flag("run_123") is True

        # Clear the flag
        await storage.clear_cancellation_flag("run_123")
        assert await storage.check_cancellation_flag("run_123") is False

    @pytest.mark.asyncio
    async def test_file_storage_clear_nonexistent_flag(self, tmp_path):
        """Test clearing a non-existent flag does not raise."""
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend(base_path=str(tmp_path / "workflow_data"))

        # Should not raise
        await storage.clear_cancellation_flag("run_nonexistent")


class TestEventReplayCancellation:
    """Test cancellation state restoration during event replay."""

    @pytest.mark.asyncio
    async def test_replay_restores_cancellation_state(self):
        """Test that CANCELLATION_REQUESTED event sets context state during replay."""
        from pyworkflow.context import LocalContext
        from pyworkflow.engine.events import create_cancellation_requested_event

        storage = InMemoryStorageBackend()

        # Create run
        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
        )
        await storage.create_run(run)

        # Record cancellation event
        event = create_cancellation_requested_event(
            run_id="run_123",
            reason="User cancelled",
        )
        await storage.record_event(event)

        # Get events
        events = await storage.get_events("run_123")

        # Create context with event log (should replay events)
        ctx = LocalContext(
            run_id="run_123",
            workflow_name="test_workflow",
            storage=storage,
            event_log=events,
            durable=True,
        )

        # Context should have cancellation requested from replay
        assert ctx.is_cancellation_requested() is True


class TestCancellationErrorHandling:
    """Test CancellationError handling in workflows."""

    @pytest.mark.asyncio
    async def test_workflow_can_catch_cancellation_for_cleanup(self):
        """Test that workflows can catch CancellationError for cleanup."""
        from pyworkflow.context import LocalContext

        cleanup_called = False

        async def workflow_with_cleanup():
            nonlocal cleanup_called
            try:
                # Simulate work that would check cancellation
                ctx = LocalContext(
                    run_id="test",
                    workflow_name="test",
                    storage=None,
                    durable=False,
                )
                ctx.request_cancellation()
                ctx.check_cancellation()
            except CancellationError:
                cleanup_called = True
                raise

        with pytest.raises(CancellationError):
            await workflow_with_cleanup()

        assert cleanup_called is True
