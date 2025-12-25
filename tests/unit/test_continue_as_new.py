"""
Unit tests for continue-as-new feature.

Tests cover:
- ContinueAsNewSignal exception
- continue_as_new() primitive function
- CONTINUED_AS_NEW status and event types
- Storage chain tracking methods
"""

import pytest

from pyworkflow import (
    CancellationError,
    LocalContext,
    MockContext,
    RunStatus,
    set_context,
)
from pyworkflow.core.exceptions import ContinueAsNewSignal
from pyworkflow.engine.events import (
    EventType,
    create_workflow_continued_as_new_event,
)
from pyworkflow.primitives.continue_as_new import continue_as_new
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import WorkflowRun


class TestContinueAsNewSignal:
    """Test ContinueAsNewSignal exception."""

    def test_signal_default_message(self):
        """Test ContinueAsNewSignal has correct default message."""
        signal = ContinueAsNewSignal()
        assert str(signal) == "Workflow continuing as new execution"

    def test_signal_stores_args(self):
        """Test ContinueAsNewSignal stores positional args."""
        signal = ContinueAsNewSignal(workflow_args=("arg1", "arg2"))
        assert signal.workflow_args == ("arg1", "arg2")

    def test_signal_stores_kwargs(self):
        """Test ContinueAsNewSignal stores keyword args."""
        signal = ContinueAsNewSignal(workflow_kwargs={"key": "value"})
        assert signal.workflow_kwargs == {"key": "value"}

    def test_signal_stores_both_args_and_kwargs(self):
        """Test ContinueAsNewSignal stores both args and kwargs."""
        signal = ContinueAsNewSignal(workflow_args=("a", "b"), workflow_kwargs={"x": 1, "y": 2})
        assert signal.workflow_args == ("a", "b")
        assert signal.workflow_kwargs == {"x": 1, "y": 2}

    def test_signal_defaults_to_empty(self):
        """Test ContinueAsNewSignal defaults to empty args/kwargs."""
        signal = ContinueAsNewSignal()
        assert signal.workflow_args == ()
        assert signal.workflow_kwargs == {}

    def test_signal_none_kwargs_becomes_empty_dict(self):
        """Test None kwargs becomes empty dict."""
        signal = ContinueAsNewSignal(workflow_kwargs=None)
        assert signal.workflow_kwargs == {}


class TestContinueAsNewPrimitive:
    """Test continue_as_new() primitive function."""

    def test_raises_runtime_error_outside_context(self):
        """Test continue_as_new raises RuntimeError outside context."""
        set_context(None)

        with pytest.raises(RuntimeError) as exc_info:
            continue_as_new("arg1")

        assert "must be called within a workflow context" in str(exc_info.value)

    def test_raises_value_error_without_args(self):
        """Test continue_as_new raises ValueError without args."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            with pytest.raises(ValueError) as exc_info:
                continue_as_new()

            assert "requires at least one argument" in str(exc_info.value)
        finally:
            set_context(None)

    def test_raises_signal_with_positional_args(self):
        """Test continue_as_new raises signal with positional args."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            with pytest.raises(ContinueAsNewSignal) as exc_info:
                continue_as_new("arg1", "arg2")

            assert exc_info.value.workflow_args == ("arg1", "arg2")
            assert exc_info.value.workflow_kwargs == {}
        finally:
            set_context(None)

    def test_raises_signal_with_keyword_args(self):
        """Test continue_as_new raises signal with keyword args."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            with pytest.raises(ContinueAsNewSignal) as exc_info:
                continue_as_new(cursor="abc123")

            assert exc_info.value.workflow_args == ()
            assert exc_info.value.workflow_kwargs == {"cursor": "abc123"}
        finally:
            set_context(None)

    def test_raises_signal_with_mixed_args(self):
        """Test continue_as_new raises signal with mixed args."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            with pytest.raises(ContinueAsNewSignal) as exc_info:
                continue_as_new("pos_arg", key1="val1", key2="val2")

            assert exc_info.value.workflow_args == ("pos_arg",)
            assert exc_info.value.workflow_kwargs == {"key1": "val1", "key2": "val2"}
        finally:
            set_context(None)

    def test_checks_cancellation_before_raising_signal(self):
        """Test continue_as_new checks cancellation first."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.request_cancellation(reason="User cancelled")
        set_context(ctx)

        try:
            with pytest.raises(CancellationError):
                continue_as_new("arg1")
        finally:
            set_context(None)


class TestContinuedAsNewStatus:
    """Test CONTINUED_AS_NEW status."""

    def test_status_exists_in_enum(self):
        """Test CONTINUED_AS_NEW exists in RunStatus enum."""
        assert hasattr(RunStatus, "CONTINUED_AS_NEW")
        assert RunStatus.CONTINUED_AS_NEW.value == "continued_as_new"

    def test_status_is_distinct_from_completed(self):
        """Test CONTINUED_AS_NEW is distinct from COMPLETED."""
        assert RunStatus.CONTINUED_AS_NEW != RunStatus.COMPLETED


class TestContinuedAsNewEvent:
    """Test WORKFLOW_CONTINUED_AS_NEW event type."""

    def test_event_type_exists(self):
        """Test WORKFLOW_CONTINUED_AS_NEW exists in EventType enum."""
        assert hasattr(EventType, "WORKFLOW_CONTINUED_AS_NEW")
        assert EventType.WORKFLOW_CONTINUED_AS_NEW.value == "workflow.continued_as_new"

    def test_create_event(self):
        """Test create_workflow_continued_as_new_event."""
        event = create_workflow_continued_as_new_event(
            run_id="run_123",
            new_run_id="run_456",
            args='["arg1", "arg2"]',
            kwargs='{"key": "value"}',
            reason="Event limit reached",
        )

        assert event.run_id == "run_123"
        assert event.type == EventType.WORKFLOW_CONTINUED_AS_NEW
        assert event.data["new_run_id"] == "run_456"
        assert event.data["args"] == '["arg1", "arg2"]'
        assert event.data["kwargs"] == '{"key": "value"}'
        assert event.data["reason"] == "Event limit reached"

    def test_create_event_minimal(self):
        """Test create_workflow_continued_as_new_event with minimal params."""
        event = create_workflow_continued_as_new_event(
            run_id="run_123",
            new_run_id="run_456",
            args="[]",
            kwargs="{}",
        )

        assert event.run_id == "run_123"
        assert event.type == EventType.WORKFLOW_CONTINUED_AS_NEW
        assert event.data.get("reason") is None


class TestWorkflowRunContinuationFields:
    """Test WorkflowRun continuation tracking fields."""

    def test_workflow_run_has_continuation_fields(self):
        """Test WorkflowRun has continued_from and continued_to fields."""
        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            continued_from_run_id="run_100",
            continued_to_run_id="run_200",
        )

        assert run.continued_from_run_id == "run_100"
        assert run.continued_to_run_id == "run_200"

    def test_workflow_run_defaults_to_none(self):
        """Test continuation fields default to None."""
        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
        )

        assert run.continued_from_run_id is None
        assert run.continued_to_run_id is None

    def test_workflow_run_to_dict_includes_continuation_fields(self):
        """Test to_dict includes continuation fields."""
        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
            continued_from_run_id="run_100",
            continued_to_run_id="run_200",
        )

        data = run.to_dict()

        assert data["continued_from_run_id"] == "run_100"
        assert data["continued_to_run_id"] == "run_200"

    def test_workflow_run_from_dict_parses_continuation_fields(self):
        """Test from_dict parses continuation fields."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        data = {
            "run_id": "run_123",
            "workflow_name": "test_workflow",
            "status": "continued_as_new",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "continued_from_run_id": "run_100",
            "continued_to_run_id": "run_200",
        }

        run = WorkflowRun.from_dict(data)

        assert run.continued_from_run_id == "run_100"
        assert run.continued_to_run_id == "run_200"


class TestStorageChainMethods:
    """Test storage backend chain tracking methods."""

    @pytest.mark.asyncio
    async def test_update_run_continuation(self):
        """Test update_run_continuation sets continued_to_run_id."""
        storage = InMemoryStorageBackend()

        run = WorkflowRun(
            run_id="run_1",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
        )
        await storage.create_run(run)

        await storage.update_run_continuation("run_1", "run_2")

        updated_run = await storage.get_run("run_1")
        assert updated_run.continued_to_run_id == "run_2"

    @pytest.mark.asyncio
    async def test_update_run_continuation_nonexistent(self):
        """Test update_run_continuation for non-existent run does not raise."""
        storage = InMemoryStorageBackend()

        # Should not raise
        await storage.update_run_continuation("nonexistent_run", "run_2")

    @pytest.mark.asyncio
    async def test_get_workflow_chain_single_run(self):
        """Test get_workflow_chain returns single run for no chain."""
        storage = InMemoryStorageBackend()

        run = WorkflowRun(
            run_id="run_1",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
        )
        await storage.create_run(run)

        chain = await storage.get_workflow_chain("run_1")

        assert len(chain) == 1
        assert chain[0].run_id == "run_1"

    @pytest.mark.asyncio
    async def test_get_workflow_chain_two_runs(self):
        """Test get_workflow_chain returns ordered chain of two runs."""
        storage = InMemoryStorageBackend()

        # Create first run
        run1 = WorkflowRun(
            run_id="run_1",
            workflow_name="test_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run1)

        # Create second run with continued_from
        run2 = WorkflowRun(
            run_id="run_2",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            continued_from_run_id="run_1",
        )
        await storage.create_run(run2)

        # Link first run to second
        await storage.update_run_continuation("run_1", "run_2")

        # Query from either run should give same chain
        chain_from_1 = await storage.get_workflow_chain("run_1")
        chain_from_2 = await storage.get_workflow_chain("run_2")

        assert len(chain_from_1) == 2
        assert len(chain_from_2) == 2
        assert chain_from_1[0].run_id == "run_1"
        assert chain_from_1[1].run_id == "run_2"
        assert chain_from_2[0].run_id == "run_1"
        assert chain_from_2[1].run_id == "run_2"

    @pytest.mark.asyncio
    async def test_get_workflow_chain_three_runs(self):
        """Test get_workflow_chain returns ordered chain of three runs."""
        storage = InMemoryStorageBackend()

        # Create chain: run_1 -> run_2 -> run_3
        run1 = WorkflowRun(
            run_id="run_1",
            workflow_name="test_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run1)

        run2 = WorkflowRun(
            run_id="run_2",
            workflow_name="test_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
            continued_from_run_id="run_1",
        )
        await storage.create_run(run2)

        run3 = WorkflowRun(
            run_id="run_3",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            continued_from_run_id="run_2",
        )
        await storage.create_run(run3)

        await storage.update_run_continuation("run_1", "run_2")
        await storage.update_run_continuation("run_2", "run_3")

        # Query from middle run
        chain = await storage.get_workflow_chain("run_2")

        assert len(chain) == 3
        assert [r.run_id for r in chain] == ["run_1", "run_2", "run_3"]

    @pytest.mark.asyncio
    async def test_get_workflow_chain_nonexistent_run(self):
        """Test get_workflow_chain returns empty list for nonexistent run."""
        storage = InMemoryStorageBackend()

        chain = await storage.get_workflow_chain("nonexistent")

        assert chain == []


class TestMockContextContinueAsNew:
    """Test MockContext with continue_as_new."""

    def test_mock_context_allows_continue_as_new(self):
        """Test continue_as_new works with MockContext."""
        ctx = MockContext(run_id="test", workflow_name="test")
        set_context(ctx)

        try:
            with pytest.raises(ContinueAsNewSignal) as exc_info:
                continue_as_new("arg1")

            assert exc_info.value.workflow_args == ("arg1",)
        finally:
            set_context(None)

    def test_mock_context_cancellation_prevents_continue_as_new(self):
        """Test MockContext cancellation prevents continue_as_new."""
        ctx = MockContext(run_id="test", workflow_name="test")
        ctx.request_cancellation()
        set_context(ctx)

        try:
            with pytest.raises(CancellationError):
                continue_as_new("arg1")
        finally:
            set_context(None)
