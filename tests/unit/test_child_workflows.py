"""
Unit tests for child workflow feature.

Tests cover:
- ChildWorkflowError and ChildWorkflowFailedError exceptions
- MaxNestingDepthError exception
- Child workflow event types
- ChildWorkflowHandle class
- Storage methods for child workflows
- Context child workflow state
"""

from datetime import UTC, datetime

import pytest

from pyworkflow import (
    ChildWorkflowError,
    ChildWorkflowFailedError,
    LocalContext,
    MaxNestingDepthError,
    WorkflowError,
)
from pyworkflow.engine.events import (
    EventType,
    create_child_workflow_cancelled_event,
    create_child_workflow_completed_event,
    create_child_workflow_failed_event,
    create_child_workflow_started_event,
)
from pyworkflow.primitives.child_handle import ChildWorkflowHandle
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


class TestChildWorkflowError:
    """Test ChildWorkflowError base exception."""

    def test_child_workflow_error_is_workflow_error(self):
        """Test ChildWorkflowError inherits from WorkflowError."""
        error = ChildWorkflowError("Test error")
        assert isinstance(error, WorkflowError)

    def test_child_workflow_error_message(self):
        """Test ChildWorkflowError has message."""
        error = ChildWorkflowError("Child workflow failed")
        assert str(error) == "Child workflow failed"


class TestChildWorkflowFailedError:
    """Test ChildWorkflowFailedError exception."""

    def test_child_workflow_failed_error_attributes(self):
        """Test ChildWorkflowFailedError stores all attributes."""
        error = ChildWorkflowFailedError(
            child_run_id="run_child123",
            child_workflow_name="payment_workflow",
            error="Payment declined",
            error_type="PaymentError",
        )
        assert error.child_run_id == "run_child123"
        assert error.child_workflow_name == "payment_workflow"
        assert error.error == "Payment declined"
        assert error.error_type == "PaymentError"

    def test_child_workflow_failed_error_message(self):
        """Test ChildWorkflowFailedError has descriptive message."""
        error = ChildWorkflowFailedError(
            child_run_id="run_child123",
            child_workflow_name="payment_workflow",
            error="Payment declined",
            error_type="PaymentError",
        )
        assert "payment_workflow" in str(error)
        assert "Payment declined" in str(error)

    def test_child_workflow_failed_error_is_child_workflow_error(self):
        """Test ChildWorkflowFailedError inherits from ChildWorkflowError."""
        error = ChildWorkflowFailedError(
            child_run_id="run_123",
            child_workflow_name="test",
            error="error",
            error_type="Error",
        )
        assert isinstance(error, ChildWorkflowError)


class TestMaxNestingDepthError:
    """Test MaxNestingDepthError exception."""

    def test_max_nesting_depth_error_attributes(self):
        """Test MaxNestingDepthError stores current depth."""
        error = MaxNestingDepthError(current_depth=3)
        assert error.current_depth == 3
        assert error.MAX_DEPTH == 3

    def test_max_nesting_depth_error_message(self):
        """Test MaxNestingDepthError has descriptive message."""
        error = MaxNestingDepthError(current_depth=3)
        assert "3" in str(error)
        assert "maximum" in str(error).lower() or "exceeded" in str(error).lower()

    def test_max_nesting_depth_error_is_child_workflow_error(self):
        """Test MaxNestingDepthError inherits from ChildWorkflowError."""
        error = MaxNestingDepthError(current_depth=3)
        assert isinstance(error, ChildWorkflowError)


class TestChildWorkflowEventTypes:
    """Test child workflow event types exist."""

    def test_child_workflow_started_event_type(self):
        """Test CHILD_WORKFLOW_STARTED event type exists."""
        assert hasattr(EventType, "CHILD_WORKFLOW_STARTED")
        assert EventType.CHILD_WORKFLOW_STARTED.value == "child_workflow.started"

    def test_child_workflow_completed_event_type(self):
        """Test CHILD_WORKFLOW_COMPLETED event type exists."""
        assert hasattr(EventType, "CHILD_WORKFLOW_COMPLETED")
        assert EventType.CHILD_WORKFLOW_COMPLETED.value == "child_workflow.completed"

    def test_child_workflow_failed_event_type(self):
        """Test CHILD_WORKFLOW_FAILED event type exists."""
        assert hasattr(EventType, "CHILD_WORKFLOW_FAILED")
        assert EventType.CHILD_WORKFLOW_FAILED.value == "child_workflow.failed"

    def test_child_workflow_cancelled_event_type(self):
        """Test CHILD_WORKFLOW_CANCELLED event type exists."""
        assert hasattr(EventType, "CHILD_WORKFLOW_CANCELLED")
        assert EventType.CHILD_WORKFLOW_CANCELLED.value == "child_workflow.cancelled"


class TestChildWorkflowEventCreation:
    """Test child workflow event creation helpers."""

    def test_create_child_workflow_started_event(self):
        """Test creating CHILD_WORKFLOW_STARTED event."""
        event = create_child_workflow_started_event(
            run_id="run_parent123",
            child_id="child_abc",
            child_run_id="run_child456",
            child_workflow_name="payment_workflow",
            args='["order-123"]',
            kwargs='{"amount": 99.99}',
            wait_for_completion=True,
        )
        assert event.run_id == "run_parent123"
        assert event.type == EventType.CHILD_WORKFLOW_STARTED
        assert event.data["child_id"] == "child_abc"
        assert event.data["child_run_id"] == "run_child456"
        assert event.data["child_workflow_name"] == "payment_workflow"
        assert event.data["wait_for_completion"] is True

    def test_create_child_workflow_completed_event(self):
        """Test creating CHILD_WORKFLOW_COMPLETED event."""
        event = create_child_workflow_completed_event(
            run_id="run_parent123",
            child_id="child_abc",
            child_run_id="run_child456",
            result='{"status": "paid"}',
        )
        assert event.run_id == "run_parent123"
        assert event.type == EventType.CHILD_WORKFLOW_COMPLETED
        assert event.data["child_id"] == "child_abc"
        assert event.data["child_run_id"] == "run_child456"
        assert event.data["result"] == '{"status": "paid"}'

    def test_create_child_workflow_failed_event(self):
        """Test creating CHILD_WORKFLOW_FAILED event."""
        event = create_child_workflow_failed_event(
            run_id="run_parent123",
            child_id="child_abc",
            child_run_id="run_child456",
            error="Payment declined",
            error_type="PaymentError",
        )
        assert event.run_id == "run_parent123"
        assert event.type == EventType.CHILD_WORKFLOW_FAILED
        assert event.data["child_id"] == "child_abc"
        assert event.data["error"] == "Payment declined"
        assert event.data["error_type"] == "PaymentError"

    def test_create_child_workflow_cancelled_event(self):
        """Test creating CHILD_WORKFLOW_CANCELLED event."""
        event = create_child_workflow_cancelled_event(
            run_id="run_parent123",
            child_id="child_abc",
            child_run_id="run_child456",
            reason="Parent completed",
        )
        assert event.run_id == "run_parent123"
        assert event.type == EventType.CHILD_WORKFLOW_CANCELLED
        assert event.data["child_id"] == "child_abc"
        assert event.data["reason"] == "Parent completed"


class TestStorageChildWorkflowMethods:
    """Test storage backend child workflow methods."""

    @pytest.fixture
    def storage(self):
        """Create a fresh storage instance."""
        return InMemoryStorageBackend()

    @pytest.mark.asyncio
    async def test_get_children_returns_empty_list(self, storage):
        """Test get_children returns empty list when no children."""
        children = await storage.get_children("run_parent123")
        assert children == []

    @pytest.mark.asyncio
    async def test_get_children_returns_children(self, storage):
        """Test get_children returns child workflows."""
        # Create parent
        parent = WorkflowRun(
            run_id="run_parent123",
            workflow_name="parent_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(parent)

        # Create children
        child1 = WorkflowRun(
            run_id="run_child1",
            workflow_name="child_workflow",
            status=RunStatus.COMPLETED,
            created_at=datetime.now(UTC),
            parent_run_id="run_parent123",
            nesting_depth=1,
        )
        child2 = WorkflowRun(
            run_id="run_child2",
            workflow_name="child_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            parent_run_id="run_parent123",
            nesting_depth=1,
        )
        await storage.create_run(child1)
        await storage.create_run(child2)

        children = await storage.get_children("run_parent123")
        assert len(children) == 2
        child_ids = {c.run_id for c in children}
        assert child_ids == {"run_child1", "run_child2"}

    @pytest.mark.asyncio
    async def test_get_children_with_status_filter(self, storage):
        """Test get_children filters by status."""
        # Create parent
        parent = WorkflowRun(
            run_id="run_parent123",
            workflow_name="parent_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(parent)

        # Create children with different statuses
        child1 = WorkflowRun(
            run_id="run_child1",
            workflow_name="child_workflow",
            status=RunStatus.COMPLETED,
            created_at=datetime.now(UTC),
            parent_run_id="run_parent123",
            nesting_depth=1,
        )
        child2 = WorkflowRun(
            run_id="run_child2",
            workflow_name="child_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            parent_run_id="run_parent123",
            nesting_depth=1,
        )
        await storage.create_run(child1)
        await storage.create_run(child2)

        # Filter by RUNNING
        running = await storage.get_children("run_parent123", status=RunStatus.RUNNING)
        assert len(running) == 1
        assert running[0].run_id == "run_child2"

        # Filter by COMPLETED
        completed = await storage.get_children("run_parent123", status=RunStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0].run_id == "run_child1"

    @pytest.mark.asyncio
    async def test_get_parent_returns_none_for_root(self, storage):
        """Test get_parent returns None for root workflow."""
        root = WorkflowRun(
            run_id="run_root",
            workflow_name="root_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(root)

        parent = await storage.get_parent("run_root")
        assert parent is None

    @pytest.mark.asyncio
    async def test_get_parent_returns_parent(self, storage):
        """Test get_parent returns parent workflow."""
        parent = WorkflowRun(
            run_id="run_parent",
            workflow_name="parent_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        child = WorkflowRun(
            run_id="run_child",
            workflow_name="child_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            parent_run_id="run_parent",
            nesting_depth=1,
        )
        await storage.create_run(parent)
        await storage.create_run(child)

        result = await storage.get_parent("run_child")
        assert result is not None
        assert result.run_id == "run_parent"

    @pytest.mark.asyncio
    async def test_get_nesting_depth_root(self, storage):
        """Test get_nesting_depth returns 0 for root."""
        root = WorkflowRun(
            run_id="run_root",
            workflow_name="root_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            nesting_depth=0,
        )
        await storage.create_run(root)

        depth = await storage.get_nesting_depth("run_root")
        assert depth == 0

    @pytest.mark.asyncio
    async def test_get_nesting_depth_child(self, storage):
        """Test get_nesting_depth returns correct depth."""
        child = WorkflowRun(
            run_id="run_child",
            workflow_name="child_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            parent_run_id="run_parent",
            nesting_depth=2,
        )
        await storage.create_run(child)

        depth = await storage.get_nesting_depth("run_child")
        assert depth == 2


class TestWorkflowRunParentChildFields:
    """Test WorkflowRun parent/child fields."""

    def test_workflow_run_default_parent_run_id_is_none(self):
        """Test WorkflowRun defaults to no parent."""
        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test",
            status=RunStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        assert run.parent_run_id is None

    def test_workflow_run_default_nesting_depth_is_zero(self):
        """Test WorkflowRun defaults to nesting depth 0."""
        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test",
            status=RunStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        assert run.nesting_depth == 0

    def test_workflow_run_with_parent(self):
        """Test WorkflowRun with parent_run_id."""
        run = WorkflowRun(
            run_id="run_child",
            workflow_name="child_workflow",
            status=RunStatus.PENDING,
            created_at=datetime.now(UTC),
            parent_run_id="run_parent",
            nesting_depth=1,
        )
        assert run.parent_run_id == "run_parent"
        assert run.nesting_depth == 1

    def test_workflow_run_to_dict_includes_parent_fields(self):
        """Test to_dict includes parent/child fields."""
        run = WorkflowRun(
            run_id="run_child",
            workflow_name="child_workflow",
            status=RunStatus.PENDING,
            created_at=datetime.now(UTC),
            parent_run_id="run_parent",
            nesting_depth=2,
        )
        data = run.to_dict()
        assert data["parent_run_id"] == "run_parent"
        assert data["nesting_depth"] == 2

    def test_workflow_run_from_dict_reads_parent_fields(self):
        """Test from_dict reads parent/child fields."""
        now = datetime.now(UTC)
        data = {
            "run_id": "run_child",
            "workflow_name": "child_workflow",
            "status": "pending",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "parent_run_id": "run_parent",
            "nesting_depth": 2,
        }
        run = WorkflowRun.from_dict(data)
        assert run.parent_run_id == "run_parent"
        assert run.nesting_depth == 2


class TestContextChildWorkflowState:
    """Test context child workflow state methods."""

    def test_local_context_has_child_result_false_initially(self):
        """Test LocalContext starts with no child results."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        assert ctx.has_child_result("child_123") is False

    def test_local_context_cache_child_result(self):
        """Test LocalContext can cache child result."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.cache_child_result(
            child_id="child_123",
            child_run_id="run_child_123",
            result={"status": "completed"},
        )
        assert ctx.has_child_result("child_123") is True

    def test_local_context_get_child_result(self):
        """Test LocalContext can get cached child result."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.cache_child_result(
            child_id="child_123",
            child_run_id="run_child_123",
            result={"status": "completed"},
        )
        result = ctx.get_child_result("child_123")
        assert result["result"] == {"status": "completed"}
        assert result["child_run_id"] == "run_child_123"

    def test_local_context_cache_failed_child_result(self):
        """Test LocalContext can cache failed child result."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.cache_child_result(
            child_id="child_123",
            child_run_id="run_child_123",
            result=None,
            failed=True,
            error="Payment failed",
            error_type="PaymentError",
        )
        result = ctx.get_child_result("child_123")
        assert result["__failed__"] is True
        assert result["error"] == "Payment failed"
        assert result["error_type"] == "PaymentError"

    def test_local_context_add_pending_child(self):
        """Test LocalContext can track pending children."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.add_pending_child("child_123", "run_child_123")
        assert "child_123" in ctx._pending_children
        assert ctx._pending_children["child_123"] == "run_child_123"


class TestChildWorkflowHandle:
    """Test ChildWorkflowHandle class."""

    @pytest.fixture
    def storage(self):
        """Create a fresh storage instance."""
        return InMemoryStorageBackend()

    def test_handle_attributes(self, storage):
        """Test ChildWorkflowHandle stores attributes."""
        handle = ChildWorkflowHandle(
            child_id="child_123",
            child_run_id="run_child_123",
            child_workflow_name="payment_workflow",
            parent_run_id="run_parent",
            _storage=storage,
        )
        assert handle.child_id == "child_123"
        assert handle.child_run_id == "run_child_123"
        assert handle.child_workflow_name == "payment_workflow"
        assert handle.parent_run_id == "run_parent"

    def test_handle_repr(self, storage):
        """Test ChildWorkflowHandle has repr."""
        handle = ChildWorkflowHandle(
            child_id="child_123",
            child_run_id="run_child_123",
            child_workflow_name="payment_workflow",
            parent_run_id="run_parent",
            _storage=storage,
        )
        repr_str = repr(handle)
        assert "child_123" in repr_str
        assert "run_child_123" in repr_str
        assert "payment_workflow" in repr_str

    @pytest.mark.asyncio
    async def test_handle_get_status(self, storage):
        """Test ChildWorkflowHandle.get_status()."""
        child = WorkflowRun(
            run_id="run_child_123",
            workflow_name="payment_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(child)

        handle = ChildWorkflowHandle(
            child_id="child_123",
            child_run_id="run_child_123",
            child_workflow_name="payment_workflow",
            parent_run_id="run_parent",
            _storage=storage,
        )
        status = await handle.get_status()
        assert status == RunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_handle_get_status_not_found(self, storage):
        """Test ChildWorkflowHandle.get_status() raises for not found."""
        handle = ChildWorkflowHandle(
            child_id="child_123",
            child_run_id="run_nonexistent",
            child_workflow_name="payment_workflow",
            parent_run_id="run_parent",
            _storage=storage,
        )
        with pytest.raises(ValueError, match="not found"):
            await handle.get_status()

    @pytest.mark.asyncio
    async def test_handle_is_running(self, storage):
        """Test ChildWorkflowHandle.is_running()."""
        child = WorkflowRun(
            run_id="run_child_123",
            workflow_name="payment_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(child)

        handle = ChildWorkflowHandle(
            child_id="child_123",
            child_run_id="run_child_123",
            child_workflow_name="payment_workflow",
            parent_run_id="run_parent",
            _storage=storage,
        )
        assert await handle.is_running() is True

    @pytest.mark.asyncio
    async def test_handle_is_terminal(self, storage):
        """Test ChildWorkflowHandle.is_terminal()."""
        child = WorkflowRun(
            run_id="run_child_123",
            workflow_name="payment_workflow",
            status=RunStatus.COMPLETED,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(child)

        handle = ChildWorkflowHandle(
            child_id="child_123",
            child_run_id="run_child_123",
            child_workflow_name="payment_workflow",
            parent_run_id="run_parent",
            _storage=storage,
        )
        assert await handle.is_terminal() is True

    @pytest.mark.asyncio
    async def test_handle_result_completed(self, storage):
        """Test ChildWorkflowHandle.result() for completed workflow."""
        child = WorkflowRun(
            run_id="run_child_123",
            workflow_name="payment_workflow",
            status=RunStatus.COMPLETED,
            created_at=datetime.now(UTC),
            result='{"status": "paid"}',
        )
        await storage.create_run(child)

        handle = ChildWorkflowHandle(
            child_id="child_123",
            child_run_id="run_child_123",
            child_workflow_name="payment_workflow",
            parent_run_id="run_parent",
            _storage=storage,
        )
        result = await handle.result(timeout=1.0)
        assert result == {"status": "paid"}

    @pytest.mark.asyncio
    async def test_handle_result_failed_raises(self, storage):
        """Test ChildWorkflowHandle.result() raises for failed workflow."""
        child = WorkflowRun(
            run_id="run_child_123",
            workflow_name="payment_workflow",
            status=RunStatus.FAILED,
            created_at=datetime.now(UTC),
            error="Payment declined",
        )
        await storage.create_run(child)

        handle = ChildWorkflowHandle(
            child_id="child_123",
            child_run_id="run_child_123",
            child_workflow_name="payment_workflow",
            parent_run_id="run_parent",
            _storage=storage,
        )
        with pytest.raises(ChildWorkflowFailedError):
            await handle.result(timeout=1.0)

    @pytest.mark.asyncio
    async def test_handle_result_cancelled_raises(self, storage):
        """Test ChildWorkflowHandle.result() raises for cancelled workflow."""
        child = WorkflowRun(
            run_id="run_child_123",
            workflow_name="payment_workflow",
            status=RunStatus.CANCELLED,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(child)

        handle = ChildWorkflowHandle(
            child_id="child_123",
            child_run_id="run_child_123",
            child_workflow_name="payment_workflow",
            parent_run_id="run_parent",
            _storage=storage,
        )
        with pytest.raises(ChildWorkflowFailedError) as exc_info:
            await handle.result(timeout=1.0)
        assert "cancelled" in str(exc_info.value.error).lower()
