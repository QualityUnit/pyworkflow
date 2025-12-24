"""
Unit tests for cancellation feature.

Tests cover:
- CancellationError exception
- Context cancellation state methods
- shield() context manager
- Storage cancellation flag methods
- Cancellation events
"""

import pytest

from pyworkflow import (
    CancellationError,
    LocalContext,
    MockContext,
    set_context,
    shield,
)
from pyworkflow.engine.events import (
    EventType,
    create_cancellation_requested_event,
    create_step_cancelled_event,
    create_workflow_cancelled_event,
)
from pyworkflow.storage.memory import InMemoryStorageBackend


class TestCancellationError:
    """Test CancellationError exception."""

    def test_cancellation_error_default_message(self):
        """Test CancellationError has default message."""
        error = CancellationError()
        assert str(error) == "Workflow was cancelled"
        assert error.reason is None

    def test_cancellation_error_custom_message(self):
        """Test CancellationError with custom message."""
        error = CancellationError("Custom cancellation message")
        assert str(error) == "Custom cancellation message"

    def test_cancellation_error_with_reason(self):
        """Test CancellationError with reason."""
        error = CancellationError("Cancelled", reason="User requested")
        assert error.reason == "User requested"

    def test_cancellation_error_is_workflow_error(self):
        """Test CancellationError inherits from WorkflowError."""
        from pyworkflow import WorkflowError

        error = CancellationError()
        assert isinstance(error, WorkflowError)


class TestContextCancellationState:
    """Test context cancellation state methods."""

    def test_local_context_cancellation_not_requested_by_default(self):
        """Test LocalContext starts with cancellation not requested."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        assert ctx.is_cancellation_requested() is False

    def test_local_context_request_cancellation(self):
        """Test LocalContext can request cancellation."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.request_cancellation()
        assert ctx.is_cancellation_requested() is True

    def test_local_context_request_cancellation_with_reason(self):
        """Test LocalContext stores cancellation reason."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.request_cancellation(reason="User clicked cancel")
        assert ctx.is_cancellation_requested() is True
        assert ctx._cancellation_reason == "User clicked cancel"

    def test_local_context_check_cancellation_raises_when_requested(self):
        """Test check_cancellation raises CancellationError when requested."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.request_cancellation(reason="Test")

        with pytest.raises(CancellationError) as exc_info:
            ctx.check_cancellation()

        assert exc_info.value.reason == "Test"

    def test_local_context_check_cancellation_does_not_raise_when_not_requested(self):
        """Test check_cancellation does not raise when not requested."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        # Should not raise
        ctx.check_cancellation()

    def test_local_context_cancellation_blocked_property(self):
        """Test cancellation_blocked property."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        assert ctx.cancellation_blocked is False

        ctx._cancellation_blocked = True
        assert ctx.cancellation_blocked is True

    def test_local_context_check_cancellation_blocked(self):
        """Test check_cancellation does not raise when blocked."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.request_cancellation()
        ctx._cancellation_blocked = True

        # Should not raise even though cancellation is requested
        ctx.check_cancellation()


class TestShieldContextManager:
    """Test shield() context manager."""

    @pytest.mark.asyncio
    async def test_shield_blocks_cancellation(self):
        """Test shield() blocks cancellation check."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            ctx.request_cancellation()

            async with shield():
                # Should not raise while shielded
                ctx.check_cancellation()

            # Should raise after shield
            with pytest.raises(CancellationError):
                ctx.check_cancellation()
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_shield_restores_previous_state(self):
        """Test shield() restores previous blocked state."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            assert ctx.cancellation_blocked is False

            async with shield():
                assert ctx.cancellation_blocked is True

            assert ctx.cancellation_blocked is False
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_shield_nested(self):
        """Test nested shield() calls work correctly."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            ctx.request_cancellation()

            async with shield():
                assert ctx.cancellation_blocked is True
                ctx.check_cancellation()  # Should not raise

                async with shield():
                    assert ctx.cancellation_blocked is True
                    ctx.check_cancellation()  # Should not raise

                # Still blocked after inner shield
                assert ctx.cancellation_blocked is True
                ctx.check_cancellation()  # Should not raise

            # Now should raise
            with pytest.raises(CancellationError):
                ctx.check_cancellation()
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_shield_without_context(self):
        """Test shield() works without workflow context (no-op)."""
        set_context(None)

        # Should not raise
        async with shield():
            pass


class TestStorageCancellationFlags:
    """Test storage backend cancellation flag methods."""

    @pytest.mark.asyncio
    async def test_memory_storage_set_cancellation_flag(self):
        """Test InMemoryStorageBackend set_cancellation_flag."""
        storage = InMemoryStorageBackend()

        await storage.set_cancellation_flag("run_123")

        assert await storage.check_cancellation_flag("run_123") is True

    @pytest.mark.asyncio
    async def test_memory_storage_check_cancellation_flag_not_set(self):
        """Test InMemoryStorageBackend returns False when flag not set."""
        storage = InMemoryStorageBackend()

        assert await storage.check_cancellation_flag("run_123") is False

    @pytest.mark.asyncio
    async def test_memory_storage_clear_cancellation_flag(self):
        """Test InMemoryStorageBackend clear_cancellation_flag."""
        storage = InMemoryStorageBackend()

        await storage.set_cancellation_flag("run_123")
        assert await storage.check_cancellation_flag("run_123") is True

        await storage.clear_cancellation_flag("run_123")
        assert await storage.check_cancellation_flag("run_123") is False

    @pytest.mark.asyncio
    async def test_memory_storage_clear_nonexistent_flag(self):
        """Test clearing a non-existent flag does not raise."""
        storage = InMemoryStorageBackend()

        # Should not raise
        await storage.clear_cancellation_flag("run_nonexistent")


class TestCancellationEvents:
    """Test cancellation event creation."""

    def test_create_cancellation_requested_event(self):
        """Test create_cancellation_requested_event."""
        event = create_cancellation_requested_event(
            run_id="run_123",
            reason="User requested",
            requested_by="admin",
        )

        assert event.run_id == "run_123"
        assert event.type == EventType.CANCELLATION_REQUESTED
        assert event.data["reason"] == "User requested"
        assert event.data["requested_by"] == "admin"

    def test_create_cancellation_requested_event_minimal(self):
        """Test create_cancellation_requested_event with minimal params."""
        event = create_cancellation_requested_event(run_id="run_123")

        assert event.run_id == "run_123"
        assert event.type == EventType.CANCELLATION_REQUESTED
        assert event.data.get("reason") is None
        assert event.data.get("requested_by") is None

    def test_create_workflow_cancelled_event(self):
        """Test create_workflow_cancelled_event."""
        event = create_workflow_cancelled_event(
            run_id="run_123",
            reason="Test cancellation",
            cleanup_completed=True,
        )

        assert event.run_id == "run_123"
        assert event.type == EventType.WORKFLOW_CANCELLED
        assert event.data["reason"] == "Test cancellation"
        assert event.data["cleanup_completed"] is True

    def test_create_workflow_cancelled_event_minimal(self):
        """Test create_workflow_cancelled_event with minimal params."""
        event = create_workflow_cancelled_event(run_id="run_123")

        assert event.run_id == "run_123"
        assert event.type == EventType.WORKFLOW_CANCELLED
        assert event.data.get("cleanup_completed") is False

    def test_create_step_cancelled_event(self):
        """Test create_step_cancelled_event."""
        event = create_step_cancelled_event(
            run_id="run_123",
            step_id="step_456",
            step_name="my_step",
        )

        assert event.run_id == "run_123"
        assert event.type == EventType.STEP_CANCELLED
        assert event.data["step_id"] == "step_456"
        assert event.data["step_name"] == "my_step"


class TestMockContextCancellation:
    """Test MockContext cancellation support."""

    def test_mock_context_cancellation_not_requested_by_default(self):
        """Test MockContext starts with cancellation not requested."""
        ctx = MockContext(run_id="test", workflow_name="test")
        assert ctx.is_cancellation_requested() is False

    def test_mock_context_request_cancellation(self):
        """Test MockContext can request cancellation."""
        ctx = MockContext(run_id="test", workflow_name="test")
        ctx.request_cancellation()
        assert ctx.is_cancellation_requested() is True

    def test_mock_context_check_cancellation(self):
        """Test MockContext check_cancellation raises when requested."""
        ctx = MockContext(run_id="test", workflow_name="test")
        ctx.request_cancellation(reason="Test")

        with pytest.raises(CancellationError):
            ctx.check_cancellation()

    def test_mock_context_cancellation_blocked(self):
        """Test MockContext cancellation blocked property."""
        ctx = MockContext(run_id="test", workflow_name="test")
        assert ctx.cancellation_blocked is False

        ctx._cancellation_blocked = True
        assert ctx.cancellation_blocked is True
