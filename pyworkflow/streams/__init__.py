"""
Streams module — pub/sub signal pattern for PyWorkflow.

Provides event-driven stream workflows where steps react to signals,
can suspend and be resumed by new signals, and emit signals back.

Public API:
    - stream_workflow: Decorator to define a named stream
    - stream_step: Decorator to define a reactive stream step
    - emit: Publish a signal to a stream
    - Signal: Signal dataclass
    - Stream: Stream dataclass
    - StreamStepContext: Context for on_signal callbacks
    - CheckpointBackend: ABC for checkpoint storage
    - get_current_signal: Get the signal that triggered current resume
    - get_checkpoint: Load saved checkpoint data
    - save_checkpoint: Save checkpoint data
"""

from pyworkflow.streams.checkpoint import (  # noqa: F401
    CheckpointBackend,
    DefaultCheckpointBackend,
    RedisCheckpointBackend,
    configure_checkpoint_backend,
    get_checkpoint_backend,
    register_checkpoint_backend,
    reset_checkpoint_backend,
)
from pyworkflow.streams.consumer import StreamConsumer, poll_once  # noqa: F401
from pyworkflow.streams.context import (  # noqa: F401
    get_checkpoint,
    get_current_signal,
    save_checkpoint,
)
from pyworkflow.streams.decorator import stream_step, stream_workflow  # noqa: F401
from pyworkflow.streams.emit import emit  # noqa: F401
from pyworkflow.streams.registry import (  # noqa: F401
    StreamMetadata,
    StreamStepMetadata,
    clear_stream_registry,
    get_steps_for_stream,
    get_stream,
    get_stream_step,
    list_stream_steps,
    list_streams,
)
from pyworkflow.streams.signal import Signal, Stream  # noqa: F401
from pyworkflow.streams.step_context import StreamStepContext  # noqa: F401

__all__ = [
    # Decorators
    "stream_workflow",
    "stream_step",
    # Core
    "emit",
    "Signal",
    "Stream",
    "StreamStepContext",
    # Context primitives
    "get_current_signal",
    "get_checkpoint",
    "save_checkpoint",
    # Checkpoint
    "CheckpointBackend",
    "DefaultCheckpointBackend",
    "RedisCheckpointBackend",
    "configure_checkpoint_backend",
    "get_checkpoint_backend",
    "register_checkpoint_backend",
    "reset_checkpoint_backend",
    # Registry
    "StreamMetadata",
    "StreamStepMetadata",
    "get_stream",
    "get_stream_step",
    "get_steps_for_stream",
    "list_streams",
    "list_stream_steps",
    "clear_stream_registry",
    # Consumer
    "StreamConsumer",
    "poll_once",
]
