"""
Persistent event loop management for Celery workers.

This module provides a single, persistent event loop per worker process.
Using a persistent loop allows asyncpg connection pools to be reused across
tasks, avoiding the overhead of creating/destroying pools for each task.

Usage:
    from pyworkflow.celery.loop import run_async

    # Instead of: result = asyncio.run(some_coroutine())
    # Use:        result = run_async(some_coroutine())
"""

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

# Per-worker persistent event loop
# Created in worker_process_init, closed in worker_shutdown
_worker_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def init_worker_loop() -> None:
    """
    Initialize the persistent event loop for this worker process.

    Called from worker_process_init signal handler.
    """
    global _worker_loop

    with _loop_lock:
        if _worker_loop is None or _worker_loop.is_closed():
            _worker_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_worker_loop)


def close_worker_loop() -> None:
    """
    Close the persistent event loop for this worker process.

    Called from worker_shutdown signal handler.
    """
    global _worker_loop

    with _loop_lock:
        if _worker_loop is not None and not _worker_loop.is_closed():
            try:
                # Run any pending cleanup
                _worker_loop.run_until_complete(_worker_loop.shutdown_asyncgens())
            except Exception:
                pass
            finally:
                _worker_loop.close()
                _worker_loop = None


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """
    Get the persistent event loop for this worker process.

    If no loop exists (e.g., running outside Celery worker), creates one.

    Returns:
        The worker's event loop
    """
    global _worker_loop

    with _loop_lock:
        if _worker_loop is None or _worker_loop.is_closed():
            # Not in a Celery worker or loop was closed - create a new one
            _worker_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_worker_loop)
        return _worker_loop


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """
    Run a coroutine on the persistent worker event loop.

    This is a drop-in replacement for asyncio.run() that reuses
    the same event loop across tasks, allowing connection pools
    to be shared.

    Args:
        coro: The coroutine to run

    Returns:
        The result of the coroutine

    Example:
        # Instead of:
        result = asyncio.run(storage.get_run(run_id))

        # Use:
        result = run_async(storage.get_run(run_id))
    """
    loop = get_worker_loop()
    return loop.run_until_complete(coro)


def is_loop_running() -> bool:
    """Check if the worker loop exists and is not closed."""
    return _worker_loop is not None and not _worker_loop.is_closed()
