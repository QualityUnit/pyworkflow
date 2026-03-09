"""
Registry for streams and stream steps.

Tracks all registered stream workflows and stream steps, enabling
lookup by name and subscription tracking.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class StreamMetadata:
    """Metadata for a registered stream."""

    name: str
    func: Callable[..., Any]
    original_func: Callable[..., Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamStepMetadata:
    """Metadata for a registered stream step."""

    name: str
    func: Callable[..., Any]
    original_func: Callable[..., Any]
    stream: str
    signal_types: list[str]
    on_signal: Callable[..., Any]
    signal_schemas: dict[str, type[BaseModel]] = field(default_factory=dict)


class StreamRegistry:
    """
    Global registry for streams and stream steps.

    Tracks @stream_workflow and @stream_step decorated functions.
    """

    def __init__(self) -> None:
        self._streams: dict[str, StreamMetadata] = {}
        self._stream_steps: dict[str, StreamStepMetadata] = {}
        self._steps_by_stream: dict[str, list[str]] = {}  # stream_name -> [step_names]

    def register_stream(
        self,
        name: str,
        func: Callable[..., Any],
        original_func: Callable[..., Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a stream workflow."""
        if name in self._streams:
            existing = self._streams[name]
            if existing.original_func is not original_func:
                raise ValueError(f"Stream name '{name}' already registered with different function")
            return

        self._streams[name] = StreamMetadata(
            name=name,
            func=func,
            original_func=original_func,
            metadata=metadata or {},
        )

    def register_stream_step(
        self,
        name: str,
        func: Callable[..., Any],
        original_func: Callable[..., Any],
        stream: str,
        signal_types: list[str],
        on_signal: Callable[..., Any],
        signal_schemas: dict[str, type[BaseModel]] | None = None,
    ) -> None:
        """Register a stream step."""
        if name in self._stream_steps:
            existing = self._stream_steps[name]
            if existing.original_func is not original_func:
                raise ValueError(
                    f"Stream step name '{name}' already registered with different function"
                )
            return

        self._stream_steps[name] = StreamStepMetadata(
            name=name,
            func=func,
            original_func=original_func,
            stream=stream,
            signal_types=signal_types,
            on_signal=on_signal,
            signal_schemas=signal_schemas or {},
        )

        # Track step-to-stream mapping
        if stream not in self._steps_by_stream:
            self._steps_by_stream[stream] = []
        if name not in self._steps_by_stream[stream]:
            self._steps_by_stream[stream].append(name)

    def get_stream(self, name: str) -> StreamMetadata | None:
        """Get stream metadata by name."""
        return self._streams.get(name)

    def get_stream_step(self, name: str) -> StreamStepMetadata | None:
        """Get stream step metadata by name."""
        return self._stream_steps.get(name)

    def get_steps_for_stream(self, stream_name: str) -> list[StreamStepMetadata]:
        """Get all stream steps registered for a given stream."""
        step_names = self._steps_by_stream.get(stream_name, [])
        return [self._stream_steps[n] for n in step_names if n in self._stream_steps]

    def list_streams(self) -> dict[str, StreamMetadata]:
        """Get all registered streams."""
        return self._streams.copy()

    def list_stream_steps(self) -> dict[str, StreamStepMetadata]:
        """Get all registered stream steps."""
        return self._stream_steps.copy()

    def clear(self) -> None:
        """Clear all registrations (useful for testing)."""
        self._streams.clear()
        self._stream_steps.clear()
        self._steps_by_stream.clear()


# Global singleton registry
_stream_registry = StreamRegistry()


def register_stream(
    name: str,
    func: Callable[..., Any],
    original_func: Callable[..., Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Register a stream in the global registry."""
    _stream_registry.register_stream(name, func, original_func, metadata)


def register_stream_step(
    name: str,
    func: Callable[..., Any],
    original_func: Callable[..., Any],
    stream: str,
    signal_types: list[str],
    on_signal: Callable[..., Any],
    signal_schemas: dict[str, type[BaseModel]] | None = None,
) -> None:
    """Register a stream step in the global registry."""
    _stream_registry.register_stream_step(
        name, func, original_func, stream, signal_types, on_signal, signal_schemas
    )


def get_stream(name: str) -> StreamMetadata | None:
    """Get stream metadata from global registry."""
    return _stream_registry.get_stream(name)


def get_stream_step(name: str) -> StreamStepMetadata | None:
    """Get stream step metadata from global registry."""
    return _stream_registry.get_stream_step(name)


def get_steps_for_stream(stream_name: str) -> list[StreamStepMetadata]:
    """Get all stream steps for a stream from global registry."""
    return _stream_registry.get_steps_for_stream(stream_name)


def list_streams() -> dict[str, StreamMetadata]:
    """List all streams in global registry."""
    return _stream_registry.list_streams()


def list_stream_steps() -> dict[str, StreamStepMetadata]:
    """List all stream steps in global registry."""
    return _stream_registry.list_stream_steps()


def clear_stream_registry() -> None:
    """Clear the global stream registry (for testing)."""
    _stream_registry.clear()
