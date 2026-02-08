"""
Unit tests for @step(force_local=True) functionality.

Tests that force_local steps:
- Are registered with the correct metadata
- Execute inline even when runtime is "celery"
- Still record durability events
- Still respect retries
- Have access to StepContext
- Produce results available to downstream steps
"""

from unittest.mock import AsyncMock, patch

import pytest

from pyworkflow.context import LocalContext, set_context
from pyworkflow.context.step_context import (
    StepContext,
    _reset_step_context,
    _set_step_context_internal,
)
from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.core.registry import _registry
from pyworkflow.core.step import _generate_step_id, step
from pyworkflow.engine.events import EventType
from pyworkflow.storage.file import FileStorageBackend


class TestForceLocalRegistration:
    """Test that force_local is properly registered in metadata."""

    def test_force_local_step_registration(self):
        """Verify a step with force_local=True is registered with force_local=True in StepMetadata."""

        @step(name="fl_registered", force_local=True)
        async def my_local_step():
            return "ok"

        step_meta = _registry.get_step("fl_registered")
        assert step_meta is not None
        assert step_meta.force_local is True

    def test_force_local_step_default(self):
        """Verify a step without force_local defaults to False."""

        @step(name="fl_default")
        async def my_default_step():
            return "ok"

        step_meta = _registry.get_step("fl_default")
        assert step_meta is not None
        assert step_meta.force_local is False

    def test_force_local_wrapper_attribute(self):
        """The wrapper function has __step_force_local__ attribute set correctly."""

        @step(name="fl_attr_true", force_local=True)
        async def local_step():
            return "ok"

        @step(name="fl_attr_false", force_local=False)
        async def remote_step():
            return "ok"

        assert hasattr(local_step, "__step_force_local__")
        assert local_step.__step_force_local__ is True

        assert hasattr(remote_step, "__step_force_local__")
        assert remote_step.__step_force_local__ is False


class TestForceLocalCeleryDispatch:
    """Test that force_local controls Celery dispatch behavior."""

    @pytest.mark.asyncio
    async def test_force_local_skips_celery_dispatch(self, tmp_path):
        """When ctx.runtime == 'celery' and force_local=True, step executes inline (NOT dispatched)."""
        executed = False

        @step(name="fl_skip_celery", force_local=True)
        async def inline_step():
            nonlocal executed
            executed = True
            return "inline_result"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run_fl",
            workflow_name="test_workflow",
            storage=storage,
        )
        # Simulate celery runtime
        ctx._runtime = "celery"
        set_context(ctx)

        try:
            result = await inline_step()
            assert result == "inline_result"
            assert executed is True
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_non_force_local_dispatches_to_celery(self, tmp_path):
        """When ctx.runtime == 'celery' and force_local=False, step IS dispatched to Celery."""

        @step(name="fl_dispatch_celery", force_local=False)
        async def remote_step():
            return "should_not_reach"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run_dispatch",
            workflow_name="test_workflow",
            storage=storage,
        )
        ctx._runtime = "celery"
        ctx._storage_config = {"backend": "file", "base_path": str(tmp_path)}
        set_context(ctx)

        try:
            # Patch _dispatch_step_to_celery to avoid needing actual Celery infrastructure.
            # The function always raises SuspensionSignal, so we replicate that.
            with (
                patch(
                    "pyworkflow.core.step._dispatch_step_to_celery",
                    new_callable=AsyncMock,
                    side_effect=SuspensionSignal(reason="step_dispatch:test", step_id="test"),
                ),
                pytest.raises(SuspensionSignal),
            ):
                await remote_step()
        finally:
            set_context(None)


class TestForceLocalViaMetadata:
    """Test that force_local can be set via metadata dict (fallback for older installs)."""

    @pytest.mark.asyncio
    async def test_metadata_force_local_skips_celery_dispatch(self, tmp_path):
        """When metadata={"force_local": True} is used instead of the dedicated parameter,
        the step still executes inline in a Celery runtime."""
        executed = False

        @step(name="fl_metadata_skip", metadata={"force_local": True})
        async def inline_via_metadata():
            nonlocal executed
            executed = True
            return "metadata_inline"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run_fl_meta",
            workflow_name="test_workflow",
            storage=storage,
        )
        ctx._runtime = "celery"
        set_context(ctx)

        try:
            result = await inline_via_metadata()
            assert result == "metadata_inline"
            assert executed is True
        finally:
            set_context(None)


class TestForceLocalDurability:
    """Test that force_local steps still record events and respect retries."""

    @pytest.mark.asyncio
    async def test_force_local_records_events(self, tmp_path):
        """Even with force_local=True, STEP_STARTED and STEP_COMPLETED events are recorded."""

        @step(name="fl_events", force_local=True)
        async def event_step():
            return "done"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run_events",
            workflow_name="test_workflow",
            storage=storage,
        )
        ctx._runtime = "celery"
        set_context(ctx)

        try:
            result = await event_step()
            assert result == "done"

            events = await storage.get_events("test_run_events")
            event_types = [e.type for e in events]
            assert EventType.STEP_STARTED in event_types
            assert EventType.STEP_COMPLETED in event_types
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_force_local_respects_retries(self, tmp_path):
        """A force_local=True step still retries on failure (raises SuspensionSignal for retry)."""
        call_count = 0

        @step(name="fl_retry", force_local=True, max_retries=2)
        async def failing_step():
            nonlocal call_count
            call_count += 1
            raise ValueError("transient error")

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run_retry",
            workflow_name="test_workflow",
            storage=storage,
        )
        ctx._runtime = "celery"
        set_context(ctx)

        try:
            # First attempt should raise SuspensionSignal (scheduling a retry)
            with pytest.raises(SuspensionSignal):
                await failing_step()

            assert call_count == 1

            # Verify STEP_FAILED and STEP_RETRYING events were recorded
            events = await storage.get_events("test_run_retry")
            event_types = [e.type for e in events]
            assert EventType.STEP_STARTED in event_types
            assert EventType.STEP_FAILED in event_types

            # The failure should be marked as retryable since max_retries > 0
            failure_events = [e for e in events if e.type == EventType.STEP_FAILED]
            assert len(failure_events) == 1
            assert failure_events[0].data["is_retryable"] is True
        finally:
            set_context(None)


class TestForceLocalStepContext:
    """Test that force_local steps have access to StepContext."""

    @pytest.mark.asyncio
    async def test_force_local_step_has_access_to_step_context(self, tmp_path):
        """A force_local=True step can read the active StepContext."""

        class MyContext(StepContext):
            tenant_id: str = ""

        captured_tenant: str | None = None

        @step(name="fl_ctx_access", force_local=True)
        async def ctx_step():
            nonlocal captured_tenant
            from pyworkflow.context.step_context import get_step_context

            ctx = get_step_context()
            captured_tenant = ctx.tenant_id
            return "ok"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run_ctx",
            workflow_name="test_workflow",
            storage=storage,
        )
        ctx._runtime = "celery"
        set_context(ctx)

        # Set up a StepContext so the step can read it
        token = _set_step_context_internal(MyContext(tenant_id="tenant-42"))

        try:
            result = await ctx_step()
            assert result == "ok"
            assert captured_tenant == "tenant-42"
        finally:
            _reset_step_context(token)
            set_context(None)


class TestForceLocalDownstreamResults:
    """Test that force_local step results are cached and available to later steps."""

    @pytest.mark.asyncio
    async def test_force_local_result_available_to_downstream_step(self, tmp_path):
        """Results from a force_local step are cached and can be consumed by a subsequent step."""

        @step(name="fl_producer", force_local=True)
        async def producer():
            return {"key": "value"}

        @step(name="fl_consumer", force_local=True)
        async def consumer(data: dict):
            return f"got-{data['key']}"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run_downstream",
            workflow_name="test_workflow",
            storage=storage,
        )
        ctx._runtime = "celery"
        set_context(ctx)

        try:
            # Execute producer then consumer (simulating a mini-workflow)
            produced = await producer()
            consumed = await consumer(produced)

            assert produced == {"key": "value"}
            assert consumed == "got-value"

            # Verify both steps recorded events
            events = await storage.get_events("test_run_downstream")
            started_events = [e for e in events if e.type == EventType.STEP_STARTED]
            completed_events = [e for e in events if e.type == EventType.STEP_COMPLETED]
            assert len(started_events) == 2
            assert len(completed_events) == 2

            # Verify producer result is cached
            producer_step_id = _generate_step_id("fl_producer", (), {})
            assert producer_step_id in ctx._step_results
            assert ctx._step_results[producer_step_id] == {"key": "value"}
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_force_local_mixed_with_regular_steps(self, tmp_path):
        """A workflow mixing force_local and regular steps works correctly in local runtime."""

        execution_order: list[str] = []

        @step(name="fl_mixed_local", force_local=True)
        async def local_step(x: int):
            execution_order.append("local")
            return x + 1

        @step(name="fl_mixed_regular", force_local=False)
        async def regular_step(x: int):
            execution_order.append("regular")
            return x * 2

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run_mixed",
            workflow_name="test_workflow",
            storage=storage,
        )
        # In local runtime (not celery), both should execute inline
        set_context(ctx)

        try:
            result1 = await local_step(5)
            result2 = await regular_step(result1)

            assert result1 == 6
            assert result2 == 12
            assert execution_order == ["local", "regular"]
        finally:
            set_context(None)
