"""
Signal dataclass for typed messages published to streams.

Signals are the message units in the stream pub/sub system. Each signal
has a type, payload, and belongs to a specific stream.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Signal:
    """
    A typed message published to a stream.

    Signals are immutable records that flow through streams. Each signal
    has a unique ID, belongs to a stream, and carries a typed payload.

    Attributes:
        signal_id: Unique identifier for this signal
        stream_id: The stream this signal belongs to
        signal_type: Type identifier (e.g., "task.created", "result.ready")
        payload: Signal data (validated against schema if configured)
        published_at: Timestamp when the signal was published
        sequence: Ordering sequence within the stream (assigned by storage)
        source_run_id: Optional run_id of the workflow that emitted this signal
        metadata: Optional additional metadata
    """

    signal_id: str = field(default_factory=lambda: f"sig_{uuid.uuid4().hex[:16]}")
    stream_id: str = ""
    signal_type: str = ""
    payload: Any = field(default_factory=dict)
    published_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    sequence: int | None = None  # Assigned by storage layer
    source_run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate signal after initialization."""
        if not self.stream_id:
            raise ValueError("Signal must have a stream_id")
        if not self.signal_type:
            raise ValueError("Signal must have a signal_type")


@dataclass
class Stream:
    """
    A named, durable channel for signals.

    Attributes:
        stream_id: Unique identifier for this stream
        status: Current stream status ("active", "paused", "closed")
        created_at: Timestamp when the stream was created
        metadata: Optional stream configuration and metadata
    """

    stream_id: str = ""
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate stream after initialization."""
        if not self.stream_id:
            raise ValueError("Stream must have a stream_id")
