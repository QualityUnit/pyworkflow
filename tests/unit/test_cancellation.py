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

    @pytest.mark.asyncio
    async def test_local_context_check_cancellation_raises_when_requested(self):
        """Test check_cancellation raises CancellationError when requested."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.request_cancellation(reason="Test")

        with pytest.raises(CancellationError) as exc_info:
            await ctx.check_cancellation()

        assert exc_info.value.reason == "Test"

    @pytest.mark.asyncio
    async def test_local_context_check_cancellation_does_not_raise_when_not_requested(self):
        """Test check_cancellation does not raise when not requested."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        # Should not raise
        await ctx.check_cancellation()

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

    @pytest.mark.asyncio
    async def test_local_context_check_cancellation_blocked(self):
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
        await ctx.check_cancellation()


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
                await ctx.check_cancellation()

            # Should raise after shield
            with pytest.raises(CancellationError):
                await ctx.check_cancellation()
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
                await ctx.check_cancellation()  # Should not raise

                async with shield():
                    assert ctx.cancellation_blocked is True
                    await ctx.check_cancellation()  # Should not raise

                # Still blocked after inner shield
                assert ctx.cancellation_blocked is True
                await ctx.check_cancellation()  # Should not raise

            # Now should raise
            with pytest.raises(CancellationError):
                await ctx.check_cancellation()
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

    @pytest.mark.asyncio
    async def test_mock_context_check_cancellation(self):
        """Test MockContext check_cancellation raises when requested."""
        ctx = MockContext(run_id="test", workflow_name="test")
        ctx.request_cancellation(reason="Test")

        with pytest.raises(CancellationError):
            await ctx.check_cancellation()

    def test_mock_context_cancellation_blocked(self):
        """Test MockContext cancellation blocked property."""
        ctx = MockContext(run_id="test", workflow_name="test")
        assert ctx.cancellation_blocked is False

        ctx._cancellation_blocked = True
        assert ctx.cancellation_blocked is True


class TestCooperativeCancellationViaStorage:
    """Test cooperative cancellation detection via storage flag."""

    @pytest.mark.asyncio
    async def test_check_cancellation_detects_storage_flag(self):
        """Test that check_cancellation detects cancellation set in storage."""
        storage = InMemoryStorageBackend()

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )

        # Not cancelled yet
        await ctx.check_cancellation()

        # Set cancellation flag externally (simulating cancel_workflow())
        await storage.set_cancellation_flag("test_run")

        # Now check_cancellation should detect it
        with pytest.raises(CancellationError):
            await ctx.check_cancellation()

        # In-memory flag should also be set now
        assert ctx.is_cancellation_requested() is True

    @pytest.mark.asyncio
    async def test_check_cancellation_skips_storage_in_transient_mode(self):
        """Test that storage is not checked in transient mode."""
        storage = InMemoryStorageBackend()

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=False,
        )

        # Set cancellation flag in storage
        await storage.set_cancellation_flag("test_run")

        # Transient mode should not check storage
        await ctx.check_cancellation()  # Should not raise

    @pytest.mark.asyncio
    async def test_check_cancellation_skips_storage_when_no_storage(self):
        """Test that storage check is skipped when no storage is configured."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=True,
        )

        # Should not raise (no storage to check)
        await ctx.check_cancellation()

    @pytest.mark.asyncio
    async def test_check_cancellation_storage_error_does_not_break_workflow(self):
        """Test that storage errors during cancellation check are handled gracefully."""
        from unittest.mock import AsyncMock

        storage = AsyncMock()
        storage.check_cancellation_flag = AsyncMock(side_effect=ConnectionError("Storage unavailable"))

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )

        # Should not raise despite storage error
        await ctx.check_cancellation()

    @pytest.mark.asyncio
    async def test_check_cancellation_blocked_skips_storage_check(self):
        """Test that storage is not checked when cancellation is blocked (shield)."""
        storage = InMemoryStorageBackend()

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )

        # Set cancellation flag in storage
        await storage.set_cancellation_flag("test_run")

        # Block cancellation (shield)
        ctx._cancellation_blocked = True

        # Should not raise while blocked
        await ctx.check_cancellation()

    @pytest.mark.asyncio
    async def test_in_memory_flag_takes_priority_over_storage(self):
        """Test that in-memory flag is checked first (fast path)."""
        storage = InMemoryStorageBackend()

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )

        # Set in-memory flag directly
        ctx.request_cancellation(reason="In-memory cancel")

        # Should raise from in-memory flag without hitting storage
        with pytest.raises(CancellationError) as exc_info:
            await ctx.check_cancellation()

        assert "In-memory cancel" in str(exc_info.value)


class TestStepContextCheckCancellation:
    """Test StepContext.check_cancellation() for distributed/tool scenarios."""

    @pytest.mark.asyncio
    async def test_step_context_detects_cancellation_via_storage(self):
        """Test StepContext.check_cancellation() detects storage flag without WorkflowContext."""
        from pyworkflow.context.step_context import StepContext

        storage = InMemoryStorageBackend()

        ctx = StepContext()
        # Inject cancellation metadata (as the framework does)
        object.__setattr__(ctx, "_cancellation_run_id", "test_run")
        object.__setattr__(ctx, "_cancellation_storage", storage)

        # Not cancelled yet
        await ctx.check_cancellation()

        # Set flag externally
        await storage.set_cancellation_flag("test_run")

        # Should detect it
        with pytest.raises(CancellationError):
            await ctx.check_cancellation()

    @pytest.mark.asyncio
    async def test_step_context_no_op_without_metadata(self):
        """Test StepContext.check_cancellation() is no-op without injected metadata."""
        from pyworkflow.context.step_context import StepContext

        ctx = StepContext()

        # Should not raise (no run_id/storage injected, no WorkflowContext)
        await ctx.check_cancellation()

    @pytest.mark.asyncio
    async def test_step_context_delegates_to_workflow_context(self):
        """Test StepContext.check_cancellation() delegates to WorkflowContext when available."""
        from pyworkflow.context.step_context import StepContext

        # Set up a WorkflowContext with cancellation requested
        wf_ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        wf_ctx.request_cancellation(reason="From workflow")
        set_context(wf_ctx)

        try:
            ctx = StepContext()

            with pytest.raises(CancellationError) as exc_info:
                await ctx.check_cancellation()

            assert "From workflow" in str(exc_info.value)
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_step_context_storage_error_handled_gracefully(self):
        """Test StepContext.check_cancellation() handles storage errors gracefully."""
        from unittest.mock import AsyncMock
        from pyworkflow.context.step_context import StepContext

        storage = AsyncMock()
        storage.check_cancellation_flag = AsyncMock(
            side_effect=ConnectionError("Storage down")
        )

        ctx = StepContext()
        object.__setattr__(ctx, "_cancellation_run_id", "test_run")
        object.__setattr__(ctx, "_cancellation_storage", storage)

        # Should not raise
        await ctx.check_cancellation()
