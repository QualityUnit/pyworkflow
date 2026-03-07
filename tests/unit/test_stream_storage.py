"""Tests for stream storage operations on InMemoryStorageBackend."""

import pytest

from pyworkflow.storage.memory import InMemoryStorageBackend


@pytest.fixture
def storage():
    """Create a fresh storage backend."""
    return InMemoryStorageBackend()


class TestStreamStorage:
    """Tests for stream CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_and_get_stream(self, storage):
        """Should create and retrieve a stream."""
        await storage.create_stream("test_stream", {"description": "test"})
        stream = await storage.get_stream("test_stream")
        assert stream is not None
        assert stream["stream_id"] == "test_stream"
        assert stream["status"] == "active"
        assert stream["metadata"] == {"description": "test"}

    @pytest.mark.asyncio
    async def test_get_nonexistent_stream(self, storage):
        """Should return None for nonexistent stream."""
        result = await storage.get_stream("nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_create_duplicate_stream(self, storage):
        """Should raise ValueError for duplicate stream_id."""
        await storage.create_stream("dup")
        with pytest.raises(ValueError, match="already exists"):
            await storage.create_stream("dup")


class TestSignalStorage:
    """Tests for signal publish/get operations."""

    @pytest.mark.asyncio
    async def test_publish_and_get_signals(self, storage):
        """Should publish signals and retrieve them in order."""
        await storage.create_stream("s1")

        seq0 = await storage.publish_signal("sig_1", "s1", "task.created", {"id": 1})
        seq1 = await storage.publish_signal("sig_2", "s1", "task.updated", {"id": 1})

        assert seq0 == 0
        assert seq1 == 1

        signals = await storage.get_signals("s1")
        assert len(signals) == 2
        assert signals[0]["signal_id"] == "sig_1"
        assert signals[1]["signal_id"] == "sig_2"

    @pytest.mark.asyncio
    async def test_get_signals_after_sequence(self, storage):
        """Should filter signals by sequence number."""
        await storage.publish_signal("s1", "stream", "t", {})
        await storage.publish_signal("s2", "stream", "t", {})
        await storage.publish_signal("s3", "stream", "t", {})

        signals = await storage.get_signals("stream", after_sequence=1)
        assert len(signals) == 2  # seq 1 and 2

    @pytest.mark.asyncio
    async def test_get_signals_with_limit(self, storage):
        """Should respect limit parameter."""
        for i in range(5):
            await storage.publish_signal(f"s{i}", "stream", "t", {})

        signals = await storage.get_signals("stream", limit=2)
        assert len(signals) == 2

    @pytest.mark.asyncio
    async def test_publish_signal_with_source_run_id(self, storage):
        """Should store source_run_id."""
        await storage.publish_signal("s1", "stream", "t", {}, source_run_id="run_123")
        signals = await storage.get_signals("stream")
        assert signals[0]["source_run_id"] == "run_123"


class TestSubscriptionStorage:
    """Tests for subscription management."""

    @pytest.mark.asyncio
    async def test_register_and_get_waiting_steps(self, storage):
        """Should register subscriptions and find waiting steps."""
        await storage.register_stream_subscription(
            "stream_1", "step_run_1", ["task.created", "task.updated"]
        )

        waiting = await storage.get_waiting_steps("stream_1", "task.created")
        assert len(waiting) == 1
        assert waiting[0]["step_run_id"] == "step_run_1"

    @pytest.mark.asyncio
    async def test_waiting_steps_filters_by_signal_type(self, storage):
        """Should only return steps subscribed to the specific signal type."""
        await storage.register_stream_subscription("s", "step_1", ["a", "b"])
        await storage.register_stream_subscription("s", "step_2", ["c"])

        waiting_a = await storage.get_waiting_steps("s", "a")
        assert len(waiting_a) == 1
        assert waiting_a[0]["step_run_id"] == "step_1"

        waiting_c = await storage.get_waiting_steps("s", "c")
        assert len(waiting_c) == 1
        assert waiting_c[0]["step_run_id"] == "step_2"

    @pytest.mark.asyncio
    async def test_update_subscription_status(self, storage):
        """Should update subscription status."""
        await storage.register_stream_subscription("s", "step_1", ["a"])
        await storage.update_subscription_status("s", "step_1", "running")

        # Should not appear in waiting steps
        waiting = await storage.get_waiting_steps("s", "a")
        assert len(waiting) == 0


class TestAcknowledgmentStorage:
    """Tests for signal acknowledgment."""

    @pytest.mark.asyncio
    async def test_acknowledge_signal(self, storage):
        """Should track acknowledged signals."""
        await storage.register_stream_subscription("s", "step_1", ["t"])
        await storage.publish_signal("sig_1", "s", "t", {})

        # Before ack: signal is pending
        pending = await storage.get_pending_signals("s", "step_1")
        assert len(pending) == 1

        # After ack: signal is no longer pending
        await storage.acknowledge_signal("sig_1", "step_1")
        pending = await storage.get_pending_signals("s", "step_1")
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_pending_signals_only_subscribed_types(self, storage):
        """Should only return pending signals for subscribed types."""
        await storage.register_stream_subscription("s", "step_1", ["a"])
        await storage.publish_signal("sig_1", "s", "a", {})
        await storage.publish_signal("sig_2", "s", "b", {})

        pending = await storage.get_pending_signals("s", "step_1")
        assert len(pending) == 1
        assert pending[0]["signal_type"] == "a"


class TestCheckpointStorage:
    """Tests for checkpoint operations."""

    @pytest.mark.asyncio
    async def test_save_and_load_checkpoint(self, storage):
        """Should save and load checkpoint data."""
        data = {"count": 42, "state": "active"}
        await storage.save_checkpoint("step_run_1", data)

        loaded = await storage.load_checkpoint("step_run_1")
        assert loaded == data

    @pytest.mark.asyncio
    async def test_load_nonexistent_checkpoint(self, storage):
        """Should return None for nonexistent checkpoint."""
        result = await storage.load_checkpoint("nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_checkpoint(self, storage):
        """Should delete checkpoint data."""
        await storage.save_checkpoint("step_run_1", {"data": True})
        await storage.delete_checkpoint("step_run_1")
        result = await storage.load_checkpoint("step_run_1")
        assert result is None

    @pytest.mark.asyncio
    async def test_overwrite_checkpoint(self, storage):
        """Should overwrite existing checkpoint."""
        await storage.save_checkpoint("step_run_1", {"version": 1})
        await storage.save_checkpoint("step_run_1", {"version": 2})
        loaded = await storage.load_checkpoint("step_run_1")
        assert loaded == {"version": 2}
