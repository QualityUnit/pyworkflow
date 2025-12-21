"""
Unit tests for @step decorator and step execution.
"""

import pytest

from pyworkflow.context import LocalContext, set_context
from pyworkflow.core.exceptions import FatalError, RetryableError, SuspensionSignal
from pyworkflow.core.step import _generate_step_id, step
from pyworkflow.engine.events import EventType
from pyworkflow.storage.file import FileStorageBackend


class TestStepDecorator:
    """Test the @step decorator."""

    def test_step_decorator_basic(self):
        """Test basic step decoration."""

        @step()
        async def simple_step():
            return "success"

        # Check that step attributes are set
        assert hasattr(simple_step, "__step__")
        assert simple_step.__step__ is True
        assert simple_step.__step_name__ == "simple_step"
        assert simple_step.__step_max_retries__ == 3  # default
        assert simple_step.__step_retry_delay__ == "exponential"  # default

    def test_step_decorator_with_name(self):
        """Test step decorator with custom name."""

        @step(name="custom_step_name")
        async def my_step():
            return "success"

        assert my_step.__step_name__ == "custom_step_name"

    def test_step_decorator_with_retries(self):
        """Test step decorator with custom retry settings."""

        @step(max_retries=5, retry_delay=10)
        async def retry_step():
            return "success"

        assert retry_step.__step_max_retries__ == 5
        assert retry_step.__step_retry_delay__ == 10

    def test_step_decorator_with_timeout(self):
        """Test step decorator with timeout."""

        @step(timeout=30)
        async def timed_step():
            return "success"

        assert timed_step.__step_timeout__ == 30

    def test_step_decorator_with_metadata(self):
        """Test step decorator with metadata."""
        metadata = {"type": "api_call", "service": "payment"}

        @step(metadata=metadata)
        async def meta_step():
            return "success"

        assert meta_step.__step_metadata__ == metadata

    @pytest.mark.asyncio
    async def test_step_outside_workflow_context(self):
        """Test that step executes directly when outside workflow context."""

        @step()
        async def direct_step(x: int):
            return x * 2

        # Should execute directly without context
        result = await direct_step(5)
        assert result == 10

    def test_step_registration(self):
        """Test that step is registered in global registry."""
        from pyworkflow.core.registry import _registry

        @step(name="registered_step")
        async def my_step():
            return "success"

        # Check that it's registered
        step_meta = _registry.get_step("registered_step")
        assert step_meta is not None
        assert step_meta.name == "registered_step"


class TestStepExecution:
    """Test step execution within workflow context."""

    @pytest.mark.asyncio
    async def test_step_execution_in_context(self, tmp_path):
        """Test step execution within a workflow context."""

        @step()
        async def context_step(value: str):
            return f"processed: {value}"

        # Create context
        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )
        set_context(ctx)

        try:
            result = await context_step("test")
            assert result == "processed: test"
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_step_caches_result(self, tmp_path):
        """Test that step results are cached in context."""
        call_count = 0

        @step()
        async def counting_step():
            nonlocal call_count
            call_count += 1
            return "result"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )
        set_context(ctx)

        try:
            # First call - should execute
            result1 = await counting_step()
            assert result1 == "result"
            assert call_count == 1

            # Generate step ID to manually cache
            step_id = _generate_step_id("counting_step", (), {})

            # Verify result is cached
            assert step_id in ctx.step_results
            assert ctx.step_results[step_id] == "result"

        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_step_uses_cached_result_on_replay(self, tmp_path):
        """Test that step uses cached result during replay."""
        call_count = 0

        @step()
        async def cached_step():
            nonlocal call_count
            call_count += 1
            return "original"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )

        # Pre-cache a result
        step_id = _generate_step_id("cached_step", (), {})
        ctx.cache_step_result(step_id, "cached_value")

        set_context(ctx)

        try:
            # Should return cached value without executing
            result = await cached_step()
            assert result == "cached_value"
            assert call_count == 0  # Should not have been called

        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_step_records_events(self, tmp_path):
        """Test that step execution records events."""

        @step()
        async def event_step():
            return "done"

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )
        set_context(ctx)

        try:
            await event_step()

            # Check events were recorded
            events = await storage.get_events("test_run")
            assert len(events) >= 2  # step.started and step.completed

            event_types = [e.type for e in events]
            assert EventType.STEP_STARTED in event_types
            assert EventType.STEP_COMPLETED in event_types

        finally:
            set_context(None)


class TestStepErrorHandling:
    """Test step error handling."""

    @pytest.mark.asyncio
    async def test_step_fatal_error(self, tmp_path):
        """Test that FatalError is recorded and raised."""

        @step()
        async def fatal_step():
            raise FatalError("Critical failure")

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )
        set_context(ctx)

        try:
            with pytest.raises(FatalError, match="Critical failure"):
                await fatal_step()

            # Check that failure event was recorded
            events = await storage.get_events("test_run")
            event_types = [e.type for e in events]
            assert EventType.STEP_FAILED in event_types

            # Find the failure event
            failure_events = [e for e in events if e.type == EventType.STEP_FAILED]
            assert len(failure_events) == 1
            assert failure_events[0].data["is_retryable"] is False

        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_step_retryable_error(self, tmp_path):
        """Test that RetryableError triggers retry scheduling (SuspensionSignal)."""

        @step()
        async def retryable_step():
            raise RetryableError("Temporary failure")

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )
        set_context(ctx)

        try:
            # In durable mode, retryable errors trigger SuspensionSignal for retry scheduling
            with pytest.raises(SuspensionSignal):
                await retryable_step()

            # Check that failure event was recorded
            events = await storage.get_events("test_run")
            failure_events = [e for e in events if e.type == EventType.STEP_FAILED]
            assert len(failure_events) == 1
            assert failure_events[0].data["is_retryable"] is True

        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_step_unexpected_error_converted_to_retryable(self, tmp_path):
        """Test that unexpected errors trigger retry scheduling (SuspensionSignal)."""

        @step()
        async def unexpected_error_step():
            raise ValueError("Unexpected")

        storage = FileStorageBackend(base_path=str(tmp_path))
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=storage,
        )
        set_context(ctx)

        try:
            # Unexpected errors are treated as retryable and trigger SuspensionSignal
            with pytest.raises(SuspensionSignal):
                await unexpected_error_step()

            # Check that failure event was recorded as retryable
            events = await storage.get_events("test_run")
            failure_events = [e for e in events if e.type == EventType.STEP_FAILED]
            assert len(failure_events) == 1
            assert failure_events[0].data["is_retryable"] is True

        finally:
            set_context(None)


class TestStepIDGeneration:
    """Test deterministic step ID generation."""

    def test_generate_step_id_same_args(self):
        """Test that same arguments produce same step ID."""
        step_id1 = _generate_step_id("test_step", (1, 2, 3), {"key": "value"})
        step_id2 = _generate_step_id("test_step", (1, 2, 3), {"key": "value"})

        assert step_id1 == step_id2

    def test_generate_step_id_different_args(self):
        """Test that different arguments produce different step IDs."""
        step_id1 = _generate_step_id("test_step", (1, 2, 3), {})
        step_id2 = _generate_step_id("test_step", (4, 5, 6), {})

        assert step_id1 != step_id2

    def test_generate_step_id_different_kwargs(self):
        """Test that different kwargs produce different step IDs."""
        step_id1 = _generate_step_id("test_step", (), {"a": 1})
        step_id2 = _generate_step_id("test_step", (), {"a": 2})

        assert step_id1 != step_id2

    def test_generate_step_id_different_name(self):
        """Test that different names produce different step IDs."""
        step_id1 = _generate_step_id("step_one", (1,), {})
        step_id2 = _generate_step_id("step_two", (1,), {})

        assert step_id1 != step_id2

    def test_generate_step_id_format(self):
        """Test step ID format."""
        step_id = _generate_step_id("my_step", (), {})

        assert step_id.startswith("step_my_step_")
        assert len(step_id) > len("step_my_step_")
