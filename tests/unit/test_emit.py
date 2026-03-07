"""Tests for emit() function and signal dispatch."""

import pytest

from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.streams.emit import emit
from pyworkflow.streams.registry import clear_stream_registry
from pyworkflow.streams.signal import Signal


@pytest.fixture
def storage():
    """Create a fresh storage backend."""
    return InMemoryStorageBackend()


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear stream registry before each test."""
    clear_stream_registry()
    yield
    clear_stream_registry()


class TestEmit:
    """Tests for the emit() function."""

    @pytest.mark.asyncio
    async def test_emit_basic(self, storage):
        """emit() should publish a signal and return it."""
        await storage.create_stream("test_stream")

        signal = await emit(
            "test_stream",
            "task.created",
            {"task_id": "t1"},
            storage=storage,
        )

        assert isinstance(signal, Signal)
        assert signal.stream_id == "test_stream"
        assert signal.signal_type == "task.created"
        assert signal.payload == {"task_id": "t1"}
        assert signal.sequence == 0

    @pytest.mark.asyncio
    async def test_emit_increments_sequence(self, storage):
        """Each emit should get a monotonically increasing sequence."""
        sig1 = await emit("s", "t", {"n": 1}, storage=storage)
        sig2 = await emit("s", "t", {"n": 2}, storage=storage)

        assert sig1.sequence == 0
        assert sig2.sequence == 1

    @pytest.mark.asyncio
    async def test_emit_stores_in_storage(self, storage):
        """emit() should persist signals in storage."""
        await emit("s", "task.created", {"id": 1}, storage=storage)
        await emit("s", "task.updated", {"id": 1}, storage=storage)

        signals = await storage.get_signals("s")
        assert len(signals) == 2
        assert signals[0]["signal_type"] == "task.created"
        assert signals[1]["signal_type"] == "task.updated"

    @pytest.mark.asyncio
    async def test_emit_with_none_payload(self, storage):
        """emit() should handle None payload as empty dict."""
        signal = await emit("s", "event", None, storage=storage)
        assert signal.payload == {}

    @pytest.mark.asyncio
    async def test_emit_with_pydantic_model(self, storage):
        """emit() should serialize Pydantic models."""
        from pydantic import BaseModel

        class TaskPayload(BaseModel):
            task_id: str
            description: str

        payload = TaskPayload(task_id="t1", description="test")
        signal = await emit("s", "task.created", payload, storage=storage)
        assert signal.payload == {"task_id": "t1", "description": "test"}

    @pytest.mark.asyncio
    async def test_emit_with_metadata(self, storage):
        """emit() should pass metadata to signal."""
        signal = await emit(
            "s",
            "t",
            {"data": True},
            storage=storage,
            metadata={"priority": "high"},
        )
        assert signal.metadata == {"priority": "high"}

    @pytest.mark.asyncio
    async def test_emit_no_storage_raises(self):
        """emit() should raise if no storage is available."""
        with pytest.raises(RuntimeError, match="No storage backend"):
            await emit("s", "t", {})

    @pytest.mark.asyncio
    async def test_emit_dispatches_to_waiting_steps(self, storage):
        """emit() should dispatch signal to waiting steps."""
        from pyworkflow.streams.decorator import stream_step

        callback_signals = []

        async def on_signal(signal, ctx):
            callback_signals.append(signal)

        @stream_step(stream="s", signals=["task.created"], on_signal=on_signal)
        async def my_step():
            pass

        # Register subscription
        await storage.register_stream_subscription("s", "stream_step_my_step_123", ["task.created"])

        await emit("s", "task.created", {"id": 1}, storage=storage)

        assert len(callback_signals) == 1
        assert callback_signals[0].signal_type == "task.created"
