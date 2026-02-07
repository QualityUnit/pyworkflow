"""
Unit tests for calling workflow primitives from within steps.

Tests cover:
- sleep() called from a @step function (durable and transient modes)
- hook() called from a @step function (should raise error)
- start_child_workflow() called from a @step function
- Polling-based wait_for_completion from step workers
- Verify step context carries storage/run_id via is_step_worker flag
- Backwards compatibility - existing step code still works
- Edge cases: transient mode, error handling
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyworkflow.context import LocalContext, MockContext, get_context, has_context, set_context
from pyworkflow.core.exceptions import ChildWorkflowFailedError
from pyworkflow.core.step import step
from pyworkflow.primitives.child_workflow import (
    _poll_child_completion,
    start_child_workflow,
)
from pyworkflow.primitives.hooks import hook
from pyworkflow.primitives.sleep import sleep
from pyworkflow.serialization.encoder import serialize
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun

# =========================================================================
# Test: is_step_worker property
# =========================================================================


class TestIsStepWorkerProperty:
    """Test the is_step_worker property on context classes."""

    def test_workflow_context_base_default_is_false(self):
        """Test that WorkflowContext.is_step_worker defaults to False."""
        # WorkflowContext is abstract, test via LocalContext
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        assert ctx.is_step_worker is False

    def test_local_context_is_step_worker_default_false(self):
        """Test that LocalContext._is_step_worker defaults to False."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        assert ctx._is_step_worker is False
        assert ctx.is_step_worker is False

    def test_local_context_is_step_worker_can_be_set(self):
        """Test that LocalContext._is_step_worker can be set to True."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx._is_step_worker = True
        assert ctx.is_step_worker is True

    def test_mock_context_is_step_worker_is_false(self):
        """Test that MockContext.is_step_worker is False (inherits from base)."""
        ctx = MockContext(run_id="test", workflow_name="test")
        assert ctx.is_step_worker is False


# =========================================================================
# Test: sleep() from step workers
# =========================================================================


class TestSleepFromStepWorker:
    """Test sleep() behavior when called from a step worker context."""

    @pytest.mark.asyncio
    async def test_sleep_uses_asyncio_sleep_on_step_worker(self):
        """Test that sleep() falls back to asyncio.sleep on step workers."""
        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with patch(
                "pyworkflow.primitives.sleep.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                await sleep(1)
                mock_sleep.assert_awaited_once_with(1)
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_sleep_does_not_suspend_on_step_worker(self):
        """Test that sleep() does NOT raise SuspensionSignal on step workers."""
        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            # This should complete without raising SuspensionSignal
            with patch("pyworkflow.primitives.sleep.asyncio.sleep", new_callable=AsyncMock):
                await sleep(1)
                # If we get here, no suspension occurred - that's correct
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_sleep_does_not_record_events_on_step_worker(self):
        """Test that sleep() does NOT record events on step workers."""
        storage = InMemoryStorageBackend()

        # Create a workflow run for the storage
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(run)

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with patch("pyworkflow.primitives.sleep.asyncio.sleep", new_callable=AsyncMock):
                await sleep(5)

            # No events should be recorded (sleep events are only for durable workflows)
            events = await storage.get_events("test_run")
            sleep_events = [e for e in events if "sleep" in e.type.value.lower()]
            assert len(sleep_events) == 0
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_sleep_with_string_duration_on_step_worker(self):
        """Test sleep() with string duration format on step workers."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with patch(
                "pyworkflow.primitives.sleep.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                await sleep("5s")
                mock_sleep.assert_awaited_once_with(5)
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_sleep_normal_workflow_still_suspends(self):
        """Test that sleep() still raises SuspensionSignal in normal workflow context."""
        from pyworkflow.core.exceptions import SuspensionSignal

        storage = InMemoryStorageBackend()

        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(run)

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        # NOT a step worker - normal workflow context
        assert ctx.is_step_worker is False
        set_context(ctx)

        try:
            with pytest.raises(SuspensionSignal):
                await sleep(10)
        finally:
            set_context(None)


# =========================================================================
# Test: hook() from step workers
# =========================================================================


class TestHookFromStepWorker:
    """Test hook() behavior when called from a step worker context."""

    @pytest.mark.asyncio
    async def test_hook_raises_error_on_step_worker(self):
        """Test that hook() raises RuntimeError on step workers."""
        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with pytest.raises(RuntimeError, match="cannot be called from within a step"):
                await hook("approval")
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_hook_error_message_is_informative(self):
        """Test that hook() error message provides helpful guidance."""
        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with pytest.raises(RuntimeError, match="workflow-level code"):
                await hook("approval")
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_hook_still_works_in_normal_workflow(self):
        """Test that hook() still works in normal workflow context (MockContext)."""
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


# =========================================================================
# Test: start_child_workflow() from step workers
# =========================================================================


class TestStartChildWorkflowFromStepWorker:
    """Test start_child_workflow() behavior when called from step workers."""

    @pytest.mark.asyncio
    async def test_wait_for_completion_polls_on_step_worker(self):
        """Test that start_child_workflow(wait_for_completion=True) polls on step workers."""
        from pyworkflow.core.workflow import workflow

        @workflow(durable=True)
        async def dummy_child():
            return {"done": True}

        storage = InMemoryStorageBackend()

        parent_run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            nesting_depth=0,
        )
        await storage.create_run(parent_run)

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with (
                patch("pyworkflow.runtime.get_runtime") as mock_get_runtime,
                patch(
                    "pyworkflow.primitives.child_workflow._poll_child_completion",
                    new_callable=AsyncMock,
                ) as mock_poll,
            ):
                mock_rt = AsyncMock()
                mock_get_runtime.return_value = mock_rt
                mock_poll.return_value = {"done": True}

                result = await start_child_workflow(dummy_child, wait_for_completion=True)
                assert result == {"done": True}
                mock_poll.assert_awaited_once()
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_wait_for_completion_does_not_suspend_on_step_worker(self):
        """Test that wait_for_completion=True does NOT raise SuspensionSignal on step workers."""
        from pyworkflow.core.workflow import workflow

        @workflow(durable=True)
        async def dummy_child():
            return {"done": True}

        storage = InMemoryStorageBackend()

        parent_run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            nesting_depth=0,
        )
        await storage.create_run(parent_run)

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with (
                patch("pyworkflow.runtime.get_runtime") as mock_get_runtime,
                patch(
                    "pyworkflow.primitives.child_workflow._poll_child_completion",
                    new_callable=AsyncMock,
                ) as mock_poll,
            ):
                mock_rt = AsyncMock()
                mock_get_runtime.return_value = mock_rt
                mock_poll.return_value = 42

                # Should NOT raise SuspensionSignal - should poll instead
                result = await start_child_workflow(dummy_child, wait_for_completion=True)
                assert result == 42
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_fire_and_forget_allowed_on_step_worker(self):
        """Test that start_child_workflow(wait_for_completion=False) works on step workers."""
        from pyworkflow.core.workflow import workflow
        from pyworkflow.primitives.child_handle import ChildWorkflowHandle

        @workflow(durable=True)
        async def dummy_child():
            return {"done": True}

        storage = InMemoryStorageBackend()

        parent_run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            nesting_depth=0,
        )
        await storage.create_run(parent_run)

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            # This should NOT raise - fire-and-forget is allowed from steps.
            # Mock get_runtime at the module where it's actually imported (inside function).
            with patch("pyworkflow.runtime.get_runtime") as mock_get_runtime:
                mock_rt = AsyncMock()
                mock_get_runtime.return_value = mock_rt

                handle = await start_child_workflow(
                    dummy_child,
                    wait_for_completion=False,
                )
                assert isinstance(handle, ChildWorkflowHandle)
                assert handle.child_workflow_name == "dummy_child"
                assert handle.parent_run_id == "test_run"
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_start_child_workflow_still_works_in_normal_workflow(self):
        """Test start_child_workflow still works in normal workflow context."""
        from pyworkflow.core.exceptions import SuspensionSignal
        from pyworkflow.core.workflow import workflow

        @workflow(durable=True)
        async def dummy_child():
            return {"done": True}

        storage = InMemoryStorageBackend()

        parent_run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            nesting_depth=0,
        )
        await storage.create_run(parent_run)

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        # NOT a step worker
        assert ctx.is_step_worker is False
        set_context(ctx)

        try:
            # Normal workflow context with wait_for_completion=True should raise
            # SuspensionSignal (waiting for child to complete)
            with patch("pyworkflow.runtime.get_runtime") as mock_get_runtime:
                mock_rt = AsyncMock()
                mock_get_runtime.return_value = mock_rt

                with pytest.raises(SuspensionSignal):
                    await start_child_workflow(dummy_child, wait_for_completion=True)
        finally:
            set_context(None)


# =========================================================================
# Test: Polling-based wait_for_completion from step workers
# =========================================================================


class TestPollChildCompletion:
    """Test _poll_child_completion() used when steps wait for child workflows."""

    @pytest.mark.asyncio
    async def test_wait_for_completion_polls_until_complete(self):
        """Test that polling returns the child workflow result when it completes."""
        storage = InMemoryStorageBackend()

        child_run = WorkflowRun(
            run_id="child_run_1",
            workflow_name="child_wf",
            status=RunStatus.COMPLETED,
            created_at=datetime.now(UTC),
            result=serialize({"answer": 42}),
        )
        await storage.create_run(child_run)

        result = await _poll_child_completion(
            storage=storage,
            child_run_id="child_run_1",
            child_workflow_name="child_wf",
            poll_interval=0.01,
        )
        assert result == {"answer": 42}

    @pytest.mark.asyncio
    async def test_wait_for_completion_polls_until_failed(self):
        """Test that polling raises ChildWorkflowFailedError when child fails."""
        storage = InMemoryStorageBackend()

        child_run = WorkflowRun(
            run_id="child_run_2",
            workflow_name="child_wf",
            status=RunStatus.FAILED,
            created_at=datetime.now(UTC),
            error="Something went wrong",
        )
        await storage.create_run(child_run)

        with pytest.raises(ChildWorkflowFailedError) as exc_info:
            await _poll_child_completion(
                storage=storage,
                child_run_id="child_run_2",
                child_workflow_name="child_wf",
                poll_interval=0.01,
            )
        assert "Something went wrong" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_wait_for_completion_timeout(self):
        """Test that polling raises TimeoutError when child doesn't finish in time."""
        storage = InMemoryStorageBackend()

        # Child stays RUNNING forever
        child_run = WorkflowRun(
            run_id="child_run_3",
            workflow_name="child_wf",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(child_run)

        with pytest.raises(TimeoutError, match="did not complete within"):
            await _poll_child_completion(
                storage=storage,
                child_run_id="child_run_3",
                child_workflow_name="child_wf",
                poll_interval=0.01,
                timeout=0.05,
            )

    @pytest.mark.asyncio
    async def test_wait_for_completion_cancelled_child(self):
        """Test that polling raises ChildWorkflowFailedError when child is cancelled."""
        storage = InMemoryStorageBackend()

        child_run = WorkflowRun(
            run_id="child_run_4",
            workflow_name="child_wf",
            status=RunStatus.CANCELLED,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(child_run)

        with pytest.raises(ChildWorkflowFailedError) as exc_info:
            await _poll_child_completion(
                storage=storage,
                child_run_id="child_run_4",
                child_workflow_name="child_wf",
                poll_interval=0.01,
            )
        assert "cancelled" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_poll_exponential_backoff(self):
        """Test that polling interval increases with exponential backoff."""
        storage = InMemoryStorageBackend()

        # Start with RUNNING, then complete after a few polls
        child_run = WorkflowRun(
            run_id="child_run_5",
            workflow_name="child_wf",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(child_run)

        sleep_durations = []
        original_sleep = asyncio.sleep

        async def tracking_sleep(duration):
            sleep_durations.append(duration)
            # After 3 polls, mark child as completed
            if len(sleep_durations) >= 3:
                await storage.update_run_status(
                    "child_run_5",
                    RunStatus.COMPLETED,
                    result=serialize("done"),
                )
            await original_sleep(0)  # Don't actually wait

        with patch(
            "pyworkflow.primitives.child_workflow.asyncio.sleep", side_effect=tracking_sleep
        ):
            result = await _poll_child_completion(
                storage=storage,
                child_run_id="child_run_5",
                child_workflow_name="child_wf",
                poll_interval=1.0,
                max_poll_interval=10.0,
            )

        assert result == "done"
        # Verify exponential backoff: 1.0, 1.5, 2.25, ...
        assert len(sleep_durations) >= 3
        assert sleep_durations[0] == 1.0
        assert sleep_durations[1] == 1.5
        assert sleep_durations[2] == pytest.approx(2.25)


# =========================================================================
# Test: WorkflowContext setup in step worker (celery/tasks.py)
# =========================================================================


class TestStepWorkerContextSetup:
    """Test that the WorkflowContext is properly set up in step workers."""

    @pytest.mark.asyncio
    async def test_context_has_correct_run_id(self):
        """Test that step worker context has the correct run_id."""
        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="wf_run_123",
            workflow_name="my_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        ctx._runtime = "celery"
        ctx._storage_config = {"type": "memory"}
        set_context(ctx)

        try:
            assert has_context()
            retrieved_ctx = get_context()
            assert retrieved_ctx.run_id == "wf_run_123"
            assert retrieved_ctx.workflow_name == "my_workflow"
            assert retrieved_ctx.is_step_worker is True
            assert retrieved_ctx.storage is storage
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_context_is_durable(self):
        """Test that step worker context is marked as durable."""
        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="wf_run_123",
            workflow_name="my_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            retrieved_ctx = get_context()
            assert retrieved_ctx.is_durable is True
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_context_has_runtime_set(self):
        """Test that step worker context has runtime set to celery."""
        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="wf_run_123",
            workflow_name="my_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        ctx._runtime = "celery"
        set_context(ctx)

        try:
            retrieved_ctx = get_context()
            assert retrieved_ctx.runtime == "celery"
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_context_has_storage_config(self):
        """Test that step worker context has storage_config set."""
        storage = InMemoryStorageBackend()
        config = {"type": "memory"}
        ctx = LocalContext(
            run_id="wf_run_123",
            workflow_name="my_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        ctx._storage_config = config
        set_context(ctx)

        try:
            retrieved_ctx = get_context()
            assert retrieved_ctx.storage_config == config
        finally:
            set_context(None)


# =========================================================================
# Test: Backwards compatibility
# =========================================================================


class TestBackwardsCompatibility:
    """Test that existing step code still works without regressions."""

    @pytest.mark.asyncio
    async def test_step_outside_context_still_works(self):
        """Test that steps called outside any context still execute directly."""

        @step()
        async def simple_step(x: int) -> int:
            return x * 2

        result = await simple_step(5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_step_in_normal_workflow_context_still_works(self, tmp_path):
        """Test that steps in normal workflow context still work."""
        from pyworkflow.storage.file import FileStorageBackend

        @step()
        async def context_step(value: str) -> str:
            return f"processed: {value}"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        set_context(ctx)

        try:
            result = await context_step("test")
            assert result == "processed: test"
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_step_in_transient_mode_still_works(self):
        """Test that steps in transient mode still work."""

        @step()
        async def transient_step(x: int) -> int:
            return x + 1

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        set_context(ctx)

        try:
            result = await transient_step(41)
            assert result == 42
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_sleep_outside_context_uses_asyncio(self):
        """Test that sleep() outside any context falls back to asyncio.sleep."""
        with patch(
            "pyworkflow.primitives.sleep.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            await sleep(1)
            mock_sleep.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_hook_outside_context_raises(self):
        """Test that hook() outside context raises RuntimeError."""
        with pytest.raises(RuntimeError, match="must be called within a workflow context"):
            await hook("approval")

    @pytest.mark.asyncio
    async def test_start_child_workflow_outside_context_raises(self):
        """Test that start_child_workflow() outside context raises RuntimeError."""
        from pyworkflow.core.workflow import workflow

        @workflow(durable=True)
        async def dummy_child():
            return {"done": True}

        with pytest.raises(RuntimeError, match="workflow context"):
            await start_child_workflow(dummy_child)


# =========================================================================
# Test: Transient mode from step worker
# =========================================================================


class TestTransientModeFromStepWorker:
    """Test behavior when step worker context is transient."""

    @pytest.mark.asyncio
    async def test_sleep_on_transient_step_worker_uses_asyncio(self):
        """Test that sleep() on a transient step worker still uses asyncio.sleep."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with patch(
                "pyworkflow.primitives.sleep.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                await sleep(2)
                mock_sleep.assert_awaited_once_with(2)
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_hook_on_transient_step_worker_raises(self):
        """Test that hook() on a transient step worker raises RuntimeError."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with pytest.raises(RuntimeError, match="cannot be called from within a step"):
                await hook("approval")
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_start_child_workflow_on_transient_step_worker_raises_no_storage(self):
        """Test that start_child_workflow on transient step worker raises for no storage."""
        from pyworkflow.core.workflow import workflow

        @workflow(durable=True)
        async def dummy_child():
            return {"done": True}

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            # wait_for_completion=False bypasses the step worker check,
            # but then fails because storage is None
            with pytest.raises(RuntimeError, match="requires durable mode"):
                await start_child_workflow(dummy_child, wait_for_completion=False)
        finally:
            set_context(None)


# =========================================================================
# Test: Event replay with step worker context
# =========================================================================


class TestEventReplayWithStepWorkerContext:
    """Test that events are properly replayed when setting up step worker context."""

    @pytest.mark.asyncio
    async def test_step_worker_context_replays_events(self):
        """Test that the step worker context replays events from the event log."""
        from pyworkflow.engine.events import create_step_completed_event

        storage = InMemoryStorageBackend()

        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(run)

        # Record a step completed event
        from pyworkflow.serialization.encoder import serialize

        event = create_step_completed_event(
            run_id="test_run",
            step_id="step_prior_1",
            step_name="prior_step",
            result=serialize(42),
        )
        await storage.record_event(event)

        # Load events and create context with event log (as celery/tasks.py does)
        events = await storage.get_events("test_run")
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
            event_log=events,
        )
        ctx._is_step_worker = True

        # The replayed event should be in step_results
        assert "step_prior_1" in ctx.step_results
        assert ctx.step_results["step_prior_1"] == 42

    @pytest.mark.asyncio
    async def test_step_worker_context_replays_child_events(self):
        """Test that child workflow events are properly replayed in step worker context."""
        from pyworkflow.engine.events import create_child_workflow_started_event

        storage = InMemoryStorageBackend()

        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(run)

        # Record a child workflow started event
        event = create_child_workflow_started_event(
            run_id="test_run",
            child_id="child_abc",
            child_run_id="run_child_123",
            child_workflow_name="child_workflow",
            args="[]",
            kwargs="{}",
            wait_for_completion=False,
        )
        await storage.record_event(event)

        # Create context with event log
        events = await storage.get_events("test_run")
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
            event_log=events,
        )
        ctx._is_step_worker = True

        # Pending children should be tracked
        assert "child_abc" in ctx.pending_children
        assert ctx.pending_children["child_abc"] == "run_child_123"


# =========================================================================
# Test: Error messages
# =========================================================================


class TestErrorMessages:
    """Test that error messages are clear and helpful."""

    @pytest.mark.asyncio
    async def test_child_workflow_from_step_polls_instead_of_error(self):
        """Test that start_child_workflow from step polls instead of raising error."""
        from pyworkflow.core.workflow import workflow

        @workflow(durable=True)
        async def dummy_child():
            return {"done": True}

        storage = InMemoryStorageBackend()
        parent_run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            nesting_depth=0,
        )
        await storage.create_run(parent_run)

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with (
                patch("pyworkflow.runtime.get_runtime") as mock_get_runtime,
                patch(
                    "pyworkflow.primitives.child_workflow._poll_child_completion",
                    new_callable=AsyncMock,
                ) as mock_poll,
            ):
                mock_rt = AsyncMock()
                mock_get_runtime.return_value = mock_rt
                mock_poll.return_value = {"done": True}

                # Should NOT raise RuntimeError - should poll instead
                result = await start_child_workflow(dummy_child, wait_for_completion=True)
                assert result == {"done": True}
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_hook_error_message_suggests_workflow_level(self):
        """Test that hook() error message suggests moving to workflow-level."""
        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
            durable=True,
        )
        ctx._is_step_worker = True
        set_context(ctx)

        try:
            with pytest.raises(RuntimeError) as exc_info:
                await hook("test_hook")
            error_msg = str(exc_info.value)
            assert "workflow-level code" in error_msg
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_start_child_workflow_context_error_message_updated(self):
        """Test that start_child_workflow error mentions step context option."""
        # When called outside any context, error should mention steps
        with pytest.raises(RuntimeError) as exc_info:
            from pyworkflow.core.workflow import workflow

            @workflow(durable=True)
            async def dummy_child():
                return {"done": True}

            await start_child_workflow(dummy_child)

        error_msg = str(exc_info.value)
        assert "step" in error_msg.lower()


# =========================================================================
# Test: Step dispatch passes workflow_name
# =========================================================================


class TestStepDispatchPassesWorkflowName:
    """Test that _dispatch_step_to_celery passes workflow_name."""

    @pytest.mark.asyncio
    async def test_dispatch_includes_workflow_name(self):
        """Test that Celery step dispatch includes workflow_name parameter."""
        from pyworkflow.core.step import _dispatch_step_to_celery

        storage = InMemoryStorageBackend()

        run = WorkflowRun(
            run_id="test_run",
            workflow_name="my_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(run)

        ctx = LocalContext(
            run_id="test_run",
            workflow_name="my_workflow",
            storage=storage,
            durable=True,
        )
        ctx._runtime = "celery"
        ctx._storage_config = {"type": "memory"}
        set_context(ctx)

        try:
            with patch("pyworkflow.celery.tasks.execute_step_task") as mock_task:
                mock_delay = MagicMock()
                mock_delay.id = "task_123"
                mock_task.delay.return_value = mock_delay

                from pyworkflow.core.exceptions import SuspensionSignal

                with pytest.raises(SuspensionSignal):
                    await _dispatch_step_to_celery(
                        ctx=ctx,
                        func=lambda: None,
                        args=(),
                        kwargs={},
                        step_name="test_step",
                        step_id="step_test_abc",
                        max_retries=3,
                        retry_delay="exponential",
                        timeout=None,
                    )

                # Check that workflow_name was passed in the delay call
                call_kwargs = mock_task.delay.call_args
                assert call_kwargs is not None
                # Check keyword arguments - workflow_name should be present
                if call_kwargs.kwargs:
                    assert call_kwargs.kwargs.get("workflow_name") == "my_workflow"
                else:
                    # All args passed as keyword args via delay()
                    raise AssertionError(f"Expected keyword args, got positional: {call_kwargs}")
        finally:
            set_context(None)
