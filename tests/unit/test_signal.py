"""Tests for Signal and Stream dataclasses."""

import pytest

from pyworkflow.streams.signal import Signal, Stream


class TestSignal:
    """Tests for the Signal dataclass."""

    def test_create_signal(self):
        """Signal should be created with required fields."""
        sig = Signal(stream_id="test_stream", signal_type="task.created")
        assert sig.stream_id == "test_stream"
        assert sig.signal_type == "task.created"
        assert sig.signal_id.startswith("sig_")
        assert sig.payload == {}
        assert sig.sequence is None
        assert sig.source_run_id is None
        assert sig.metadata == {}

    def test_signal_with_payload(self):
        """Signal should accept arbitrary payload."""
        payload = {"task_id": "t1", "description": "Do something"}
        sig = Signal(
            stream_id="test_stream",
            signal_type="task.created",
            payload=payload,
        )
        assert sig.payload == payload

    def test_signal_with_metadata(self):
        """Signal should accept metadata."""
        sig = Signal(
            stream_id="test_stream",
            signal_type="task.created",
            metadata={"priority": "high"},
        )
        assert sig.metadata == {"priority": "high"}

    def test_signal_requires_stream_id(self):
        """Signal must have a stream_id."""
        with pytest.raises(ValueError, match="stream_id"):
            Signal(signal_type="task.created")

    def test_signal_requires_signal_type(self):
        """Signal must have a signal_type."""
        with pytest.raises(ValueError, match="signal_type"):
            Signal(stream_id="test_stream")

    def test_signal_unique_ids(self):
        """Each signal should get a unique ID."""
        sig1 = Signal(stream_id="s", signal_type="t")
        sig2 = Signal(stream_id="s", signal_type="t")
        assert sig1.signal_id != sig2.signal_id


class TestStream:
    """Tests for the Stream dataclass."""

    def test_create_stream(self):
        """Stream should be created with required fields."""
        stream = Stream(stream_id="test_stream")
        assert stream.stream_id == "test_stream"
        assert stream.status == "active"
        assert stream.metadata == {}

    def test_stream_requires_stream_id(self):
        """Stream must have a stream_id."""
        with pytest.raises(ValueError, match="stream_id"):
            Stream()

    def test_stream_with_metadata(self):
        """Stream should accept metadata."""
        stream = Stream(stream_id="s", metadata={"description": "test"})
        assert stream.metadata == {"description": "test"}
