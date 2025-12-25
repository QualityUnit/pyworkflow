"""
Integration tests for continue-as-new feature.

Tests cover:
- Workflow continues as new and new run executes
- Chain of multiple continuations tracked correctly
- Cancellation prevents continuation
- Error handling during continuation
- get_workflow_chain() function
"""

from datetime import UTC, datetime

import pytest

from pyworkflow import (
    CancellationError,
    RunStatus,
    continue_as_new,
    get_workflow_chain,
)
from pyworkflow.config import configure, reset_config
from pyworkflow.context import LocalContext, set_context
from pyworkflow.core.exceptions import ContinueAsNewSignal
from pyworkflow.engine.events import EventType
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import WorkflowRun


@pytest.fixture
def storage():
    """Create in-memory storage for tests."""
    return InMemoryStorageBackend()


@pytest.fixture(autouse=True)
def setup_config(storage):
    """Configure pyworkflow with in-memory storage."""
    configure(storage=storage, default_durable=True)
    yield
    reset_config()


class TestContinueAsNewExecution:
    """Test continue_as_new execution flow."""

    @pytest.mark.asyncio
    async def test_continue_as_new_raises_signal(self, storage):
        """Test that continue_as_new raises ContinueAsNewSignal."""
        # Execute workflow - it should raise ContinueAsNewSignal
        ctx = LocalContext(
            run_id="run_1",
            workflow_name="counter_workflow",
            storage=storage,
            durable=True,
        )
        set_context(ctx)

        try:
            with pytest.raises(ContinueAsNewSignal) as exc_info:
                continue_as_new(count=2)

            # Check the signal has correct args
            assert exc_info.value.workflow_kwargs == {"count": 2}
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_storage_links_runs_correctly(self, storage):
        """Test that storage properly links continuation runs."""
        # Create initial run
        run1 = WorkflowRun(
            run_id="run_1",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run1)

        # Create continuation run with link
        run2 = WorkflowRun(
            run_id="run_2",
            workflow_name="my_workflow",
            status=RunStatus.RUNNING,
            continued_from_run_id="run_1",
        )
        await storage.create_run(run2)

        # Update old run to point to new
        await storage.update_run_continuation("run_1", "run_2")

        # Check old run is updated
        old_run = await storage.get_run("run_1")
        assert old_run.status == RunStatus.CONTINUED_AS_NEW
        assert old_run.continued_to_run_id == "run_2"

        # Check new run is linked back
        new_run = await storage.get_run("run_2")
        assert new_run is not None
        assert new_run.continued_from_run_id == "run_1"
        assert new_run.workflow_name == "my_workflow"

    @pytest.mark.asyncio
    async def test_continuation_event_recorded(self, storage):
        """Test that WORKFLOW_CONTINUED_AS_NEW event is recorded."""
        from pyworkflow.engine.events import create_workflow_continued_as_new_event

        # Create initial run
        run = WorkflowRun(
            run_id="run_1",
            workflow_name="my_workflow",
            status=RunStatus.RUNNING,
        )
        await storage.create_run(run)

        # Record continuation event manually (simulating what executor does)
        continuation_event = create_workflow_continued_as_new_event(
            run_id="run_1",
            new_run_id="run_2",
            args=serialize_args(42),
            kwargs=serialize_kwargs(key="value"),
        )
        await storage.record_event(continuation_event)

        # Check event was recorded
        events = await storage.get_events("run_1")
        continuation_events = [e for e in events if e.type == EventType.WORKFLOW_CONTINUED_AS_NEW]
        assert len(continuation_events) == 1

        event = continuation_events[0]
        assert event.data["new_run_id"] == "run_2"
        assert event.data["args"] == serialize_args(42)
        assert event.data["kwargs"] == serialize_kwargs(key="value")


class TestWorkflowChain:
    """Test workflow chain tracking."""

    @pytest.mark.asyncio
    async def test_get_workflow_chain_returns_ordered_list(self, storage):
        """Test get_workflow_chain returns runs in order."""
        # Create a chain of runs: run_1 -> run_2 -> run_3
        run1 = WorkflowRun(
            run_id="run_1",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(run1)

        run2 = WorkflowRun(
            run_id="run_2",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
            continued_from_run_id="run_1",
            created_at=datetime.now(UTC),
        )
        await storage.create_run(run2)

        run3 = WorkflowRun(
            run_id="run_3",
            workflow_name="my_workflow",
            status=RunStatus.COMPLETED,
            continued_from_run_id="run_2",
            created_at=datetime.now(UTC),
        )
        await storage.create_run(run3)

        # Link runs
        await storage.update_run_continuation("run_1", "run_2")
        await storage.update_run_continuation("run_2", "run_3")

        # Query chain from any run
        chain = await get_workflow_chain("run_2", storage=storage)

        assert len(chain) == 3
        assert [r.run_id for r in chain] == ["run_1", "run_2", "run_3"]

    @pytest.mark.asyncio
    async def test_chain_from_first_run(self, storage):
        """Test getting chain from first run returns full chain."""
        # Create chain
        run1 = WorkflowRun(
            run_id="first",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run1)

        run2 = WorkflowRun(
            run_id="second",
            workflow_name="my_workflow",
            status=RunStatus.RUNNING,
            continued_from_run_id="first",
        )
        await storage.create_run(run2)

        await storage.update_run_continuation("first", "second")

        chain = await get_workflow_chain("first", storage=storage)

        assert len(chain) == 2
        assert chain[0].run_id == "first"
        assert chain[1].run_id == "second"

    @pytest.mark.asyncio
    async def test_chain_from_last_run(self, storage):
        """Test getting chain from last run returns full chain."""
        # Create chain
        run1 = WorkflowRun(
            run_id="first",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run1)

        run2 = WorkflowRun(
            run_id="last",
            workflow_name="my_workflow",
            status=RunStatus.RUNNING,
            continued_from_run_id="first",
        )
        await storage.create_run(run2)

        await storage.update_run_continuation("first", "last")

        chain = await get_workflow_chain("last", storage=storage)

        assert len(chain) == 2
        assert chain[0].run_id == "first"
        assert chain[1].run_id == "last"


class TestCancellationPreventsContination:
    """Test that cancellation prevents continue_as_new."""

    @pytest.mark.asyncio
    async def test_cancelled_workflow_cannot_continue_as_new(self):
        """Test that continue_as_new raises CancellationError when cancelled."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx.request_cancellation(reason="User cancelled")
        set_context(ctx)

        try:
            # Should raise CancellationError, not ContinueAsNewSignal
            with pytest.raises(CancellationError):
                continue_as_new("arg1")
        finally:
            set_context(None)


class TestContinueAsNewWithArgs:
    """Test continue_as_new with various argument patterns."""

    @pytest.mark.asyncio
    async def test_continue_with_positional_args(self):
        """Test continue_as_new with positional args."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            with pytest.raises(ContinueAsNewSignal) as exc_info:
                continue_as_new("a", "b", "c")

            assert exc_info.value.workflow_args == ("a", "b", "c")
            assert exc_info.value.workflow_kwargs == {}
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_continue_with_keyword_args(self):
        """Test continue_as_new with keyword args."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            with pytest.raises(ContinueAsNewSignal) as exc_info:
                continue_as_new(cursor="abc", limit=100)

            assert exc_info.value.workflow_args == ()
            assert exc_info.value.workflow_kwargs == {"cursor": "abc", "limit": 100}
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_continue_with_complex_args(self):
        """Test continue_as_new with complex types."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            complex_data = {"items": [1, 2, 3], "metadata": {"key": "value"}}

            with pytest.raises(ContinueAsNewSignal) as exc_info:
                continue_as_new(data=complex_data)

            assert exc_info.value.workflow_kwargs["data"] == complex_data
        finally:
            set_context(None)


class TestFileStorageChain:
    """Test chain methods with FileStorageBackend."""

    @pytest.mark.asyncio
    async def test_file_storage_workflow_chain(self, tmp_path):
        """Test get_workflow_chain with FileStorageBackend."""
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend(base_path=str(tmp_path / "workflow_data"))

        # Create chain
        run1 = WorkflowRun(
            run_id="run_1",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run1)

        run2 = WorkflowRun(
            run_id="run_2",
            workflow_name="my_workflow",
            status=RunStatus.RUNNING,
            continued_from_run_id="run_1",
        )
        await storage.create_run(run2)

        await storage.update_run_continuation("run_1", "run_2")

        # Get chain
        chain = await storage.get_workflow_chain("run_2")

        assert len(chain) == 2
        assert chain[0].run_id == "run_1"
        assert chain[1].run_id == "run_2"

    @pytest.mark.asyncio
    async def test_file_storage_update_continuation(self, tmp_path):
        """Test update_run_continuation with FileStorageBackend."""
        from pyworkflow.storage.file import FileStorageBackend

        storage = FileStorageBackend(base_path=str(tmp_path / "workflow_data"))

        # Create run
        run = WorkflowRun(
            run_id="run_1",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run)

        # Update continuation
        await storage.update_run_continuation("run_1", "run_2")

        # Verify
        updated_run = await storage.get_run("run_1")
        assert updated_run.continued_to_run_id == "run_2"


class TestContinuedAsNewStatus:
    """Test CONTINUED_AS_NEW status handling."""

    @pytest.mark.asyncio
    async def test_continued_as_new_is_terminal(self, storage):
        """Test that CONTINUED_AS_NEW is treated as terminal status."""
        from pyworkflow import cancel_workflow

        run = WorkflowRun(
            run_id="run_1",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run)

        # Trying to cancel should return False (terminal state)
        result = await cancel_workflow("run_1", storage=storage)
        assert result is False

    @pytest.mark.asyncio
    async def test_list_runs_includes_continued_as_new(self, storage):
        """Test that list_runs can filter by CONTINUED_AS_NEW status."""
        # Create runs with different statuses
        run1 = WorkflowRun(
            run_id="run_1",
            workflow_name="my_workflow",
            status=RunStatus.COMPLETED,
        )
        await storage.create_run(run1)

        run2 = WorkflowRun(
            run_id="run_2",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run2)

        run3 = WorkflowRun(
            run_id="run_3",
            workflow_name="my_workflow",
            status=RunStatus.CONTINUED_AS_NEW,
        )
        await storage.create_run(run3)

        # Filter by CONTINUED_AS_NEW
        runs, _ = await storage.list_runs(status=RunStatus.CONTINUED_AS_NEW)

        assert len(runs) == 2
        assert all(r.status == RunStatus.CONTINUED_AS_NEW for r in runs)
