"""
Unit tests for hooks feature.

Tests cover:
- Hook primitive function
- MockContext hook behavior
- TypedHook with Pydantic validation
- resume_hook functionality (event-based idempotency)
- Token parsing helpers
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ValidationError

from pyworkflow import (
    HookAlreadyReceivedError,
    HookExpiredError,
    HookNotFoundError,
    InvalidTokenError,
    MockContext,
    ResumeResult,
    define_hook,
    hook,
    resume_hook,
    set_context,
)
from pyworkflow.engine.events import create_hook_created_event, create_hook_received_event
from pyworkflow.primitives.resume_hook import (
    create_hook_token,
    parse_hook_token,
)
from pyworkflow.storage.memory import InMemoryStorageBackend


class TestHookPrimitive:
    """Test the hook() primitive function."""

    @pytest.mark.asyncio
    async def test_hook_requires_context(self):
        """Test that hook() raises error without workflow context."""
        with pytest.raises(RuntimeError, match="must be called within a workflow context"):
            await hook("test_hook")

    @pytest.mark.asyncio
    async def test_hook_with_mock_context(self):
        """Test hook() with MockContext returns mock payload."""
        ctx = MockContext(
            run_id="test_run",
            workflow_name="test_workflow",
            mock_hooks={"approval": {"approved": True}},
        )
        set_context(ctx)

        try:
            result = await hook("approval")
            assert result == {"approved": True}
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_hook_generates_composite_token(self):
        """Test hook() generates composite token in format run_id:hook_id."""
        ctx = MockContext(
            run_id="test_run",
            workflow_name="test_workflow",
        )
        set_context(ctx)

        try:
            await hook("approval")

            # Check that composite token was generated
            assert len(ctx.hooks) == 1
            token = ctx.hooks[0]["token"]
            assert token.startswith("test_run:")
            assert "approval" in token
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_hook_with_timeout(self):
        """Test hook() with timeout parameter."""
        ctx = MockContext(
            run_id="test_run",
            workflow_name="test_workflow",
        )
        set_context(ctx)

        try:
            await hook("approval", timeout="24h")

            # Check that timeout was tracked (parsed to seconds)
            assert ctx.hooks[0]["timeout"] == 86400  # 24 hours in seconds
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_hook_with_on_created_callback(self):
        """Test hook() with on_created callback receives composite token."""
        callback_called = False
        callback_token = None

        async def on_created(token: str):
            nonlocal callback_called, callback_token
            callback_called = True
            callback_token = token

        ctx = MockContext(
            run_id="test_run",
            workflow_name="test_workflow",
        )
        set_context(ctx)

        try:
            await hook("approval", on_created=on_created)

            assert callback_called
            # Token should be composite format: run_id:hook_id
            assert callback_token.startswith("test_run:")
        finally:
            set_context(None)


class TestMockContextHooks:
    """Test MockContext hook tracking."""

    @pytest.mark.asyncio
    async def test_mock_context_tracks_hooks(self):
        """Test that MockContext tracks all hook calls."""
        ctx = MockContext(run_id="test", workflow_name="test")
        set_context(ctx)

        try:
            await hook("hook1")
            await hook("hook2")
            await hook("hook3")

            assert ctx.hook_count == 3
            assert ctx.hook_names == ["hook1", "hook2", "hook3"]
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_mock_context_default_payload(self):
        """Test that MockContext returns default mock payload."""
        ctx = MockContext(run_id="test", workflow_name="test")
        set_context(ctx)

        try:
            result = await hook("unknown_hook")
            assert result == {"hook": "unknown_hook", "mock": True}
        finally:
            set_context(None)

    def test_mock_context_reset_clears_hooks(self):
        """Test that reset() clears hook tracking."""
        ctx = MockContext(run_id="test", workflow_name="test")
        ctx._hooks.append({"name": "test_hook", "token": "abc", "timeout": None})

        ctx.reset()

        assert ctx.hook_count == 0
        assert ctx.hooks == []


class TestTypedHook:
    """Test TypedHook with Pydantic validation."""

    @pytest.mark.asyncio
    async def test_typed_hook_validates_payload(self):
        """Test that TypedHook validates payload against schema."""

        class ApprovalPayload(BaseModel):
            approved: bool
            reviewer: str

        approval = define_hook("approval", ApprovalPayload)

        ctx = MockContext(
            run_id="test",
            workflow_name="test",
            mock_hooks={"approval": {"approved": True, "reviewer": "john"}},
        )
        set_context(ctx)

        try:
            result = await approval()
            assert isinstance(result, ApprovalPayload)
            assert result.approved is True
            assert result.reviewer == "john"
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_typed_hook_raises_validation_error(self):
        """Test that TypedHook raises ValidationError for invalid payload."""

        class ApprovalPayload(BaseModel):
            approved: bool
            reviewer: str

        approval = define_hook("approval", ApprovalPayload)

        ctx = MockContext(
            run_id="test",
            workflow_name="test",
            mock_hooks={"approval": {"approved": "not_a_bool"}},  # Missing reviewer
        )
        set_context(ctx)

        try:
            with pytest.raises(ValidationError):
                await approval()
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_typed_hook_with_timeout(self):
        """Test TypedHook with timeout parameter."""

        class Payload(BaseModel):
            data: str

        my_hook = define_hook("my_hook", Payload)

        ctx = MockContext(
            run_id="test",
            workflow_name="test",
            mock_hooks={"my_hook": {"data": "test_data"}},
        )
        set_context(ctx)

        try:
            result = await my_hook(timeout="1h")
            assert result.data == "test_data"

            # Check tracking - token should be composite format
            assert ctx.hooks[0]["token"].startswith("test:")
            assert ctx.hooks[0]["timeout"] == 3600
        finally:
            set_context(None)

    def test_typed_hook_repr(self):
        """Test TypedHook string representation."""

        class MyPayload(BaseModel):
            value: int

        my_hook = define_hook("test_hook", MyPayload)
        assert repr(my_hook) == "TypedHook(name='test_hook', schema=MyPayload)"


class TestResumeHook:
    """Test resume_hook functionality with event-based idempotency."""

    @pytest.mark.asyncio
    async def test_resume_hook_invalid_token_format(self):
        """Test resume_hook raises error for invalid token format."""
        storage = InMemoryStorageBackend()

        with pytest.raises(InvalidTokenError):
            await resume_hook("invalid_token_no_colon", {"data": "test"}, storage=storage)

    @pytest.mark.asyncio
    async def test_resume_hook_not_found(self):
        """Test resume_hook raises error for unknown token (no HOOK_CREATED event)."""
        storage = InMemoryStorageBackend()

        # Create a run but no hook event
        from pyworkflow.storage.schemas import RunStatus, WorkflowRun

        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test_workflow",
            status=RunStatus.SUSPENDED,
        )
        await storage.create_run(run)

        # Use valid composite token format but non-existent hook
        with pytest.raises(HookNotFoundError):
            await resume_hook("run_123:hook_456", {"data": "test"}, storage=storage)

    @pytest.mark.asyncio
    async def test_resume_hook_already_received(self):
        """Test resume_hook raises error for already received hook."""
        storage = InMemoryStorageBackend()

        # Create run
        from pyworkflow.storage.schemas import RunStatus, WorkflowRun

        run = WorkflowRun(
            run_id="run_456",
            workflow_name="test_workflow",
            status=RunStatus.SUSPENDED,
        )
        await storage.create_run(run)

        # Record HOOK_CREATED event
        event = create_hook_created_event(
            run_id="run_456",
            hook_id="hook_123",
            hook_name="approval",
            token="run_456:hook_123",
        )
        await storage.record_event(event)

        # Record HOOK_RECEIVED event (already received)
        received_event = create_hook_received_event(
            run_id="run_456",
            hook_id="hook_123",
            payload="{}",
        )
        await storage.record_event(received_event)

        with pytest.raises(HookAlreadyReceivedError):
            await resume_hook("run_456:hook_123", {"data": "test"}, storage=storage)

    @pytest.mark.asyncio
    async def test_resume_hook_expired(self):
        """Test resume_hook raises error for expired hook."""
        storage = InMemoryStorageBackend()

        # Create run
        from pyworkflow.storage.schemas import RunStatus, WorkflowRun

        run = WorkflowRun(
            run_id="run_456",
            workflow_name="test_workflow",
            status=RunStatus.SUSPENDED,
        )
        await storage.create_run(run)

        # Record HOOK_CREATED event with past expiration
        past_time = datetime.now(UTC) - timedelta(hours=1)
        event = create_hook_created_event(
            run_id="run_456",
            hook_id="hook_123",
            hook_name="approval",
            token="run_456:hook_123",
            expires_at=past_time,
        )
        await storage.record_event(event)

        with pytest.raises(HookExpiredError):
            await resume_hook("run_456:hook_123", {"data": "test"}, storage=storage)

    @pytest.mark.asyncio
    async def test_resume_hook_success(self):
        """Test successful hook resumption."""
        storage = InMemoryStorageBackend()

        # Create run
        from pyworkflow.storage.schemas import RunStatus, WorkflowRun

        run = WorkflowRun(
            run_id="run_456",
            workflow_name="test_workflow",
            status=RunStatus.SUSPENDED,
        )
        await storage.create_run(run)

        # Record HOOK_CREATED event
        event = create_hook_created_event(
            run_id="run_456",
            hook_id="hook_123",
            hook_name="approval",
            token="run_456:hook_123",
        )
        await storage.record_event(event)

        # Resume the hook using composite token
        result = await resume_hook("run_456:hook_123", {"approved": True}, storage=storage)

        assert isinstance(result, ResumeResult)
        assert result.run_id == "run_456"
        assert result.hook_id == "hook_123"
        assert result.status == "resumed"

        # Check HOOK_RECEIVED event was recorded
        events = await storage.get_events("run_456")
        hook_received_events = [e for e in events if e.type.value == "hook.received"]
        assert len(hook_received_events) == 1
        assert hook_received_events[0].data["hook_id"] == "hook_123"

    @pytest.mark.asyncio
    async def test_resume_hook_with_expiration_not_expired(self):
        """Test resume_hook succeeds when expiration is in the future."""
        storage = InMemoryStorageBackend()

        # Create run
        from pyworkflow.storage.schemas import RunStatus, WorkflowRun

        run = WorkflowRun(
            run_id="run_456",
            workflow_name="test_workflow",
            status=RunStatus.SUSPENDED,
        )
        await storage.create_run(run)

        # Record HOOK_CREATED event with future expiration
        future_time = datetime.now(UTC) + timedelta(hours=1)
        event = create_hook_created_event(
            run_id="run_456",
            hook_id="hook_123",
            hook_name="approval",
            token="run_456:hook_123",
            expires_at=future_time,
        )
        await storage.record_event(event)

        # Should succeed
        result = await resume_hook("run_456:hook_123", {"approved": True}, storage=storage)
        assert result.status == "resumed"

    @pytest.mark.asyncio
    async def test_resume_hook_requires_storage(self):
        """Test resume_hook raises error without configured storage."""
        # Reset any global config
        from pyworkflow.config import reset_config

        reset_config()

        with pytest.raises(RuntimeError, match="No storage backend configured"):
            await resume_hook("run_123:hook_456", {"data": "test"})


class TestTokenParsing:
    """Test token parsing helper functions."""

    def test_parse_valid_token(self):
        """Test parsing a valid composite token."""
        run_id, hook_id = parse_hook_token("run_abc123:hook_approval_1")
        assert run_id == "run_abc123"
        assert hook_id == "hook_approval_1"

    def test_parse_token_with_colons_in_hook_id(self):
        """Test parsing token where hook_id contains colons."""
        run_id, hook_id = parse_hook_token("run_abc:hook:with:colons")
        assert run_id == "run_abc"
        assert hook_id == "hook:with:colons"

    def test_parse_token_no_separator(self):
        """Test parsing token without separator raises error."""
        with pytest.raises(InvalidTokenError, match="Invalid token format"):
            parse_hook_token("invalid_token_no_colon")

    def test_parse_token_empty_run_id(self):
        """Test parsing token with empty run_id raises error."""
        with pytest.raises(InvalidTokenError, match="Invalid token format"):
            parse_hook_token(":hook_123")

    def test_parse_token_empty_hook_id(self):
        """Test parsing token with empty hook_id raises error."""
        with pytest.raises(InvalidTokenError, match="Invalid token format"):
            parse_hook_token("run_123:")

    def test_create_token(self):
        """Test creating composite token."""
        token = create_hook_token("run_abc123", "hook_approval_1")
        assert token == "run_abc123:hook_approval_1"

    def test_roundtrip_token(self):
        """Test token creation and parsing roundtrip."""
        original_run_id = "run_xyz789"
        original_hook_id = "hook_payment_2"

        token = create_hook_token(original_run_id, original_hook_id)
        parsed_run_id, parsed_hook_id = parse_hook_token(token)

        assert parsed_run_id == original_run_id
        assert parsed_hook_id == original_hook_id


class TestHookExceptions:
    """Test hook-related exception classes."""

    def test_hook_not_found_error(self):
        """Test HookNotFoundError contains token."""
        error = HookNotFoundError("my_token_123")
        assert error.token == "my_token_123"
        assert "my_token_123" in str(error)

    def test_hook_already_received_error(self):
        """Test HookAlreadyReceivedError contains hook_id."""
        error = HookAlreadyReceivedError("hook_abc")
        assert error.hook_id == "hook_abc"
        assert "hook_abc" in str(error)

    def test_hook_expired_error(self):
        """Test HookExpiredError contains hook_id."""
        error = HookExpiredError("hook_xyz")
        assert error.hook_id == "hook_xyz"
        assert "hook_xyz" in str(error)
