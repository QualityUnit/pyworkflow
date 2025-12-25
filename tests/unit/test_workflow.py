"""
Unit tests for @workflow decorator and workflow execution.
"""

import pytest

from pyworkflow.context import LocalContext, get_context, has_context, set_context
from pyworkflow.core.workflow import execute_workflow_with_context, workflow
from pyworkflow.storage.file import FileStorageBackend


class TestWorkflowDecorator:
    """Test the @workflow decorator."""

    def test_workflow_decorator_basic(self):
        """Test basic workflow decoration."""

        @workflow()
        async def simple_workflow():
            return "success"

        # Check that workflow attributes are set
        assert hasattr(simple_workflow, "__workflow__")
        assert simple_workflow.__workflow__ is True
        assert simple_workflow.__workflow_name__ == "simple_workflow"

    def test_workflow_decorator_with_name(self):
        """Test workflow decorator with custom name."""

        @workflow(name="custom_name")
        async def my_workflow():
            return "success"

        assert my_workflow.__workflow_name__ == "custom_name"

    def test_workflow_decorator_with_max_duration(self):
        """Test workflow decorator with max_duration."""

        @workflow(max_duration="2h")
        async def timed_workflow():
            return "success"

        assert timed_workflow.__workflow_max_duration__ == "2h"

    def test_workflow_decorator_with_tags(self):
        """Test workflow decorator with tags."""
        tags = ["backend", "critical"]

        @workflow(tags=tags)
        async def tagged_workflow():
            return "success"

        assert tagged_workflow.__workflow_tags__ == tags

    def test_workflow_decorator_with_too_many_tags(self):
        """Test workflow decorator rejects more than 3 tags."""
        with pytest.raises(ValueError, match="at most 3 tags"):

            @workflow(tags=["a", "b", "c", "d"])
            async def too_many_tags_workflow():
                return "success"

    @pytest.mark.asyncio
    async def test_workflow_execution(self):
        """Test basic workflow execution."""

        @workflow()
        async def test_workflow(x: int):
            return x * 2

        result = await test_workflow(5)
        assert result == 10

    def test_workflow_registration(self):
        """Test that workflow is registered in global registry."""
        from pyworkflow.core.registry import get_workflow

        @workflow(name="registered_workflow")
        async def my_workflow():
            return "success"

        # Check that it's registered
        workflow_meta = get_workflow("registered_workflow")
        assert workflow_meta is not None
        assert workflow_meta.name == "registered_workflow"

    @pytest.mark.asyncio
    async def test_workflow_with_args_and_kwargs(self):
        """Test workflow with various argument types."""

        @workflow()
        async def args_workflow(a: int, b: int, c: int = 10):
            return a + b + c

        result = await args_workflow(1, 2, c=3)
        assert result == 6


class TestWorkflowExecution:
    """Test workflow execution with context."""

    @pytest.mark.asyncio
    async def test_execute_workflow_with_context(self, tmp_path):
        """Test executing a workflow with proper context setup."""

        @workflow()
        async def context_workflow(value: str):
            ctx = get_context()
            assert ctx.run_id == "test_run_123"
            assert ctx.workflow_name == "test_workflow"
            return f"processed: {value}"

        # Create storage backend
        storage = FileStorageBackend(base_path=str(tmp_path))

        # Execute with context
        result = await execute_workflow_with_context(
            workflow_func=context_workflow,
            run_id="test_run_123",
            workflow_name="test_workflow",
            storage=storage,
            args=("test_value",),
            kwargs={},
        )

        assert result == "processed: test_value"

    @pytest.mark.asyncio
    async def test_context_cleared_after_execution(self, tmp_path):
        """Test that context is cleared after workflow execution."""

        @workflow()
        async def cleanup_workflow():
            return "done"

        storage = FileStorageBackend(base_path=str(tmp_path))

        await execute_workflow_with_context(
            workflow_func=cleanup_workflow,
            run_id="test_run",
            workflow_name="cleanup_test",
            storage=storage,
            args=(),
            kwargs={},
        )

        # Context should be cleared
        assert not has_context()

    @pytest.mark.asyncio
    async def test_workflow_exception_handling(self, tmp_path):
        """Test that workflow exceptions are properly handled."""

        @workflow()
        async def failing_workflow():
            raise ValueError("Test error")

        storage = FileStorageBackend(base_path=str(tmp_path))

        with pytest.raises(ValueError, match="Test error"):
            await execute_workflow_with_context(
                workflow_func=failing_workflow,
                run_id="test_run",
                workflow_name="failing_test",
                storage=storage,
                args=(),
                kwargs={},
            )

        # Context should still be cleared after exception
        assert not has_context()

    @pytest.mark.asyncio
    async def test_workflow_event_recording(self, tmp_path):
        """Test that workflow execution records events."""

        @workflow()
        async def event_workflow():
            return "completed"

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = "test_run_events"

        await execute_workflow_with_context(
            workflow_func=event_workflow,
            run_id=run_id,
            workflow_name="event_test",
            storage=storage,
            args=(),
            kwargs={},
        )

        # Check that events were recorded
        events = await storage.get_events(run_id)
        assert len(events) >= 1

        # Should have workflow.completed event
        event_types = [e.type.value for e in events]
        assert "workflow.completed" in event_types

    @pytest.mark.asyncio
    async def test_workflow_with_nested_context(self, tmp_path):
        """Test workflow execution restores previous context."""
        from pyworkflow.context import reset_context

        # Set up an initial context
        initial_storage = FileStorageBackend(base_path=str(tmp_path / "initial"))
        initial_ctx = LocalContext(
            run_id="initial_run",
            workflow_name="initial_workflow",
            storage=initial_storage,
        )
        initial_token = set_context(initial_ctx)

        try:

            @workflow()
            async def nested_workflow():
                ctx = get_context()
                # This should be the new context
                assert ctx.run_id == "nested_run"
                return "nested"

            storage = FileStorageBackend(base_path=str(tmp_path / "nested"))

            result = await execute_workflow_with_context(
                workflow_func=nested_workflow,
                run_id="nested_run",
                workflow_name="nested_test",
                storage=storage,
                args=(),
                kwargs={},
            )

            assert result == "nested"

            # After execution, context should be restored to initial
            # (token-based reset restores previous context)
            assert has_context()
            ctx = get_context()
            assert ctx.run_id == "initial_run"
        finally:
            reset_context(initial_token)
