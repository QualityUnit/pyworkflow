"""Tests for stream workflow and stream step decorators and registry."""

import pytest

from pyworkflow.streams.decorator import stream_step, stream_workflow
from pyworkflow.streams.registry import (
    clear_stream_registry,
    get_steps_for_stream,
    get_stream,
    get_stream_step,
    list_stream_steps,
    list_streams,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the stream registry before each test."""
    clear_stream_registry()
    yield
    clear_stream_registry()


class TestStreamWorkflowDecorator:
    """Tests for the @stream_workflow decorator."""

    def test_basic_stream_workflow(self):
        """@stream_workflow should register a stream."""

        @stream_workflow(name="test_stream")
        async def my_stream():
            pass

        assert my_stream.__stream_workflow__ is True
        assert my_stream.__stream_name__ == "test_stream"

    def test_stream_workflow_default_name(self):
        """@stream_workflow should default to function name."""

        @stream_workflow()
        async def agent_comms():
            pass

        assert agent_comms.__stream_name__ == "agent_comms"
        meta = get_stream("agent_comms")
        assert meta is not None
        assert meta.name == "agent_comms"

    def test_stream_workflow_registry(self):
        """Registered streams should be queryable."""

        @stream_workflow(name="stream_a")
        async def a():
            pass

        @stream_workflow(name="stream_b")
        async def b():
            pass

        streams = list_streams()
        assert "stream_a" in streams
        assert "stream_b" in streams

    def test_stream_workflow_duplicate_same_func(self):
        """Re-registering same function should be idempotent."""

        @stream_workflow(name="dup_stream")
        async def my_stream():
            pass

        # Should not raise
        meta = get_stream("dup_stream")
        assert meta is not None


class TestStreamStepDecorator:
    """Tests for the @stream_step decorator."""

    def test_basic_stream_step(self):
        """@stream_step should register a stream step."""

        async def handle_signal(signal, ctx):
            pass

        @stream_step(
            stream="test_stream",
            signals=["task.created"],
            on_signal=handle_signal,
        )
        async def task_planner():
            pass

        assert task_planner.__stream_step__ is True
        assert task_planner.__stream_step_name__ == "task_planner"
        assert task_planner.__stream_name__ == "test_stream"
        assert task_planner.__signal_types__ == ["task.created"]

    def test_stream_step_with_multiple_signals(self):
        """@stream_step should accept multiple signal types."""

        async def handler(signal, ctx):
            pass

        @stream_step(
            stream="comms",
            signals=["task.created", "task.updated", "task.deleted"],
            on_signal=handler,
        )
        async def multi_handler():
            pass

        meta = get_stream_step("multi_handler")
        assert meta is not None
        assert meta.signal_types == ["task.created", "task.updated", "task.deleted"]

    def test_stream_step_with_schema_dict(self):
        """@stream_step should accept dict mapping signal_type to Pydantic schema."""
        from pydantic import BaseModel

        class TaskPayload(BaseModel):
            task_id: str
            description: str

        async def handler(signal, ctx):
            pass

        @stream_step(
            stream="comms",
            signals={"task.created": TaskPayload},
            on_signal=handler,
        )
        async def schema_step():
            pass

        meta = get_stream_step("schema_step")
        assert meta is not None
        assert meta.signal_types == ["task.created"]
        assert meta.signal_schemas == {"task.created": TaskPayload}

    def test_stream_step_custom_name(self):
        """@stream_step should support custom name."""

        async def handler(signal, ctx):
            pass

        @stream_step(
            stream="comms",
            signals=["event"],
            on_signal=handler,
            name="custom_name",
        )
        async def original_name():
            pass

        meta = get_stream_step("custom_name")
        assert meta is not None
        assert meta.name == "custom_name"

    def test_steps_for_stream(self):
        """get_steps_for_stream should return steps registered for a stream."""

        async def handler(signal, ctx):
            pass

        @stream_step(stream="shared", signals=["a"], on_signal=handler)
        async def step_a():
            pass

        @stream_step(stream="shared", signals=["b"], on_signal=handler)
        async def step_b():
            pass

        @stream_step(stream="other", signals=["c"], on_signal=handler)
        async def step_c():
            pass

        shared_steps = get_steps_for_stream("shared")
        assert len(shared_steps) == 2
        names = [s.name for s in shared_steps]
        assert "step_a" in names
        assert "step_b" in names

        other_steps = get_steps_for_stream("other")
        assert len(other_steps) == 1
        assert other_steps[0].name == "step_c"

    def test_list_all_stream_steps(self):
        """list_stream_steps should return all registered steps."""

        async def handler(signal, ctx):
            pass

        @stream_step(stream="s1", signals=["a"], on_signal=handler)
        async def sa():
            pass

        @stream_step(stream="s2", signals=["b"], on_signal=handler)
        async def sb():
            pass

        all_steps = list_stream_steps()
        assert "sa" in all_steps
        assert "sb" in all_steps
