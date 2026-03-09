"""End-to-end tests for stream step lifecycle."""

import pytest

from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.streams.checkpoint import reset_checkpoint_backend
from pyworkflow.streams.context import (
    get_checkpoint,
    get_current_signal,
    reset_stream_step_context,
    save_checkpoint,
    set_stream_step_context,
)
from pyworkflow.streams.decorator import stream_step
from pyworkflow.streams.emit import emit
from pyworkflow.streams.registry import clear_stream_registry
from pyworkflow.streams.signal import Signal
from pyworkflow.streams.step_context import StreamStepContext


@pytest.fixture
def storage():
    """Create a fresh storage backend."""
    return InMemoryStorageBackend()


@pytest.fixture(autouse=True)
def clean_state():
    """Clean up registry and checkpoint backend between tests."""
    clear_stream_registry()
    reset_checkpoint_backend()
    yield
    clear_stream_registry()
    reset_checkpoint_backend()


class TestStreamStepLifecycle:
    """Tests for the full stream step lifecycle."""

    @pytest.mark.asyncio
    async def test_on_signal_callback_invoked(self, storage):
        """on_signal should be called when a matching signal arrives."""
        received = []

        async def on_signal(signal, ctx):
            received.append(signal.signal_type)

        @stream_step(stream="s", signals=["task.created"], on_signal=on_signal)
        async def worker():
            pass

        await storage.register_stream_subscription("s", "stream_step_worker_1", ["task.created"])

        await emit("s", "task.created", {"id": 1}, storage=storage)
        assert received == ["task.created"]

    @pytest.mark.asyncio
    async def test_on_signal_resume_triggers_lifecycle(self, storage):
        """ctx.resume() in on_signal should mark step for resumption."""
        resume_called = []

        async def on_signal(signal, ctx):
            resume_called.append(True)
            await ctx.resume()

        @stream_step(stream="s", signals=["task.created"], on_signal=on_signal)
        async def worker():
            pass

        await storage.register_stream_subscription("s", "stream_step_worker_1", ["task.created"])

        await emit("s", "task.created", {"id": 1}, storage=storage)
        assert len(resume_called) == 1

    @pytest.mark.asyncio
    async def test_on_signal_no_resume_stays_suspended(self, storage):
        """Without ctx.resume(), step should stay suspended."""
        processed = []

        async def on_signal(signal, ctx):
            processed.append(signal.signal_type)
            # No ctx.resume() - just process the signal

        @stream_step(stream="s", signals=["event"], on_signal=on_signal)
        async def worker():
            pass

        await storage.register_stream_subscription("s", "stream_step_worker_1", ["event"])

        await emit("s", "event", {}, storage=storage)
        assert len(processed) == 1

        # Subscription should still be waiting
        sub = storage._subscriptions.get(("s", "stream_step_worker_1"))
        assert sub is not None
        assert sub["status"] == "waiting"

    @pytest.mark.asyncio
    async def test_on_signal_cancel(self, storage):
        """ctx.cancel() should cancel the step."""

        async def on_signal(signal, ctx):
            await ctx.cancel("test reason")

        @stream_step(stream="s", signals=["event"], on_signal=on_signal)
        async def worker():
            pass

        await storage.register_stream_subscription("s", "stream_step_worker_1", ["event"])

        await emit("s", "event", {}, storage=storage)
        # Cancel was called - step should be marked

    @pytest.mark.asyncio
    async def test_multiple_signal_types(self, storage):
        """Step should only receive signals it subscribes to."""
        received_types = []

        async def on_signal(signal, ctx):
            received_types.append(signal.signal_type)

        @stream_step(
            stream="s",
            signals=["task.created", "task.updated"],
            on_signal=on_signal,
        )
        async def worker():
            pass

        await storage.register_stream_subscription(
            "s", "stream_step_worker_1", ["task.created", "task.updated"]
        )

        await emit("s", "task.created", {}, storage=storage)
        await emit("s", "task.deleted", {}, storage=storage)  # Not subscribed
        await emit("s", "task.updated", {}, storage=storage)

        assert received_types == ["task.created", "task.updated"]


class TestStreamStepContext:
    """Tests for StreamStepContext in on_signal callbacks."""

    @pytest.mark.asyncio
    async def test_context_status(self):
        """StreamStepContext should expose status."""
        ctx = StreamStepContext(
            status="suspended",
            run_id="run_1",
            stream_id="s1",
        )
        assert ctx.status == "suspended"
        assert ctx.run_id == "run_1"
        assert ctx.stream_id == "s1"

    @pytest.mark.asyncio
    async def test_context_resume(self):
        """resume() should set should_resume flag."""
        ctx = StreamStepContext(status="suspended", run_id="r", stream_id="s")
        assert not ctx.should_resume
        await ctx.resume()
        assert ctx.should_resume

    @pytest.mark.asyncio
    async def test_context_cancel(self):
        """cancel() should set cancelled flag and reason."""
        ctx = StreamStepContext(status="suspended", run_id="r", stream_id="s")
        assert not ctx.is_cancelled
        await ctx.cancel("done")
        assert ctx.is_cancelled
        assert ctx.cancel_reason == "done"


class TestCheckpointIntegration:
    """Tests for checkpoint save/load within stream step context."""

    @pytest.mark.asyncio
    async def test_save_and_load_checkpoint(self, storage):
        """Should save and load checkpoint via context functions."""
        tokens = set_stream_step_context(
            step_run_id="step_1",
            stream_id="s1",
            storage=storage,
        )
        try:
            # No checkpoint initially
            data = await get_checkpoint()
            assert data is None

            # Save checkpoint
            await save_checkpoint({"count": 42, "state": "processing"})

            # Load it back
            data = await get_checkpoint()
            assert data == {"count": 42, "state": "processing"}

            # Overwrite
            await save_checkpoint({"count": 43, "state": "done"})
            data = await get_checkpoint()
            assert data == {"count": 43, "state": "done"}
        finally:
            reset_stream_step_context(tokens)

    @pytest.mark.asyncio
    async def test_get_current_signal_none_on_first_run(self, storage):
        """get_current_signal() should return None on first start."""
        tokens = set_stream_step_context(
            step_run_id="step_1",
            stream_id="s1",
            signal=None,
            storage=storage,
        )
        try:
            signal = await get_current_signal()
            assert signal is None
        finally:
            reset_stream_step_context(tokens)

    @pytest.mark.asyncio
    async def test_get_current_signal_with_signal(self, storage):
        """get_current_signal() should return the signal on resume."""
        test_signal = Signal(
            stream_id="s1",
            signal_type="task.created",
            payload={"task_id": "t1"},
        )
        tokens = set_stream_step_context(
            step_run_id="step_1",
            stream_id="s1",
            signal=test_signal,
            storage=storage,
        )
        try:
            signal = await get_current_signal()
            assert signal is not None
            assert signal.signal_type == "task.created"
            assert signal.payload == {"task_id": "t1"}
        finally:
            reset_stream_step_context(tokens)


class TestSignalPayloadValidation:
    """Tests for Pydantic schema validation on signal payloads."""

    @pytest.mark.asyncio
    async def test_valid_payload_schema(self, storage):
        """Valid payload should pass schema validation."""
        from pydantic import BaseModel

        class TaskPayload(BaseModel):
            task_id: str
            description: str

        validated = []

        async def on_signal(signal, ctx):
            validated.append(signal.payload)

        @stream_step(
            stream="s",
            signals={"task.created": TaskPayload},
            on_signal=on_signal,
        )
        async def worker():
            pass

        await storage.register_stream_subscription("s", "stream_step_worker_1", ["task.created"])

        await emit(
            "s",
            "task.created",
            {"task_id": "t1", "description": "Test task"},
            storage=storage,
        )

        assert len(validated) == 1
        # Payload was validated as TaskPayload
        assert validated[0].task_id == "t1"
        assert validated[0].description == "Test task"

    @pytest.mark.asyncio
    async def test_invalid_payload_schema(self, storage):
        """Invalid payload should be rejected (not dispatched)."""
        from pydantic import BaseModel

        class StrictPayload(BaseModel):
            required_field: str

        received = []

        async def on_signal(signal, ctx):
            received.append(True)

        @stream_step(
            stream="s",
            signals={"task.created": StrictPayload},
            on_signal=on_signal,
        )
        async def worker():
            pass

        await storage.register_stream_subscription("s", "stream_step_worker_1", ["task.created"])

        # Missing required_field - should fail validation
        await emit("s", "task.created", {"wrong_field": "value"}, storage=storage)

        # on_signal should NOT have been called due to validation failure
        assert len(received) == 0
