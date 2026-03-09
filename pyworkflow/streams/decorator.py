"""
@stream_workflow and @stream_step decorators for defining streams and reactive steps.

@stream_workflow defines a named stream channel.
@stream_step defines a long-lived reactive step that subscribes to signals on a stream.
"""

import functools
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from pyworkflow.streams.registry import register_stream, register_stream_step


def stream_workflow(
    name: str | None = None,
    **metadata: Any,
) -> Callable:
    """
    Decorator to define a stream (named channel for signals).

    Args:
        name: Stream name (defaults to function name)
        **metadata: Additional stream metadata

    Returns:
        Decorated function with stream metadata

    Examples:
        @stream_workflow(name="agent_comms")
        async def agent_communication():
            pass
    """

    def decorator(func: Callable) -> Callable:
        stream_name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        register_stream(
            name=stream_name,
            func=wrapper,
            original_func=func,
            metadata=metadata,
        )

        wrapper.__stream_workflow__ = True  # type: ignore[attr-defined]
        wrapper.__stream_name__ = stream_name  # type: ignore[attr-defined]

        return wrapper

    return decorator


def stream_step(
    stream: str,
    signals: list[str] | dict[str, type[BaseModel]],
    on_signal: Callable[..., Any],
    name: str | None = None,
) -> Callable:
    """
    Decorator to define a stream step (long-lived reactive unit).

    A stream step has two code paths:
    1. The on_signal callback: runs on every matching signal arrival
    2. The lifecycle function (decorated): runs on start and each explicit resume

    Args:
        stream: Name of the stream to subscribe to
        signals: Signal types to subscribe to. Either:
            - list[str]: Signal type names
            - dict[str, BaseModel]: Signal type -> Pydantic schema mapping
        on_signal: Async callback for signal processing
        name: Step name (defaults to function name)

    Returns:
        Decorated function with stream step metadata

    Examples:
        async def handle_signal(signal, ctx):
            if signal.signal_type == "task.created":
                await ctx.resume()

        @stream_step(
            stream="agent_comms",
            signals=["task.created", "task.updated"],
            on_signal=handle_signal,
        )
        async def task_planner():
            signal = await get_current_signal()
            if signal:
                await process(signal)
    """

    # Parse signal types and schemas
    if isinstance(signals, dict):
        signal_types = list(signals.keys())
        signal_schemas = signals
    else:
        signal_types = list(signals)
        signal_schemas = {}

    def decorator(func: Callable) -> Callable:
        step_name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        register_stream_step(
            name=step_name,
            func=wrapper,
            original_func=func,
            stream=stream,
            signal_types=signal_types,
            on_signal=on_signal,
            signal_schemas=signal_schemas,
        )

        wrapper.__stream_step__ = True  # type: ignore[attr-defined]
        wrapper.__stream_step_name__ = step_name  # type: ignore[attr-defined]
        wrapper.__stream_name__ = stream  # type: ignore[attr-defined]
        wrapper.__signal_types__ = signal_types  # type: ignore[attr-defined]

        return wrapper

    return decorator
