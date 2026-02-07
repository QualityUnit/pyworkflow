"""
Persistent event loop management for Celery workers.

This module provides a single, persistent event loop per worker process.
Using a persistent loop allows asyncpg connection pools to be reused across
tasks, avoiding the overhead of creating/destroying pools for each task.

Thread-safety:
    When using --pool=threads, multiple Celery threads may call run_async()
    concurrently. The event loop runs on a dedicated background thread, and
    run_async() uses asyncio.run_coroutine_threadsafe() to submit coroutines
    from any thread safely.

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
_loop_thread: threading.Thread | None = None


def _run_loop_forever(loop: asyncio.AbstractEventLoop) -> None:
    """Run the event loop on a background thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def init_worker_loop() -> None:
    """
    Initialize the persistent event loop for this worker process.

    Called from worker_process_init signal handler.
    The loop runs on a dedicated background daemon thread so that
    run_async() can safely submit coroutines from any worker thread.
    """
    global _worker_loop, _loop_thread

    with _loop_lock:
        if _worker_loop is None or _worker_loop.is_closed():
            _worker_loop = asyncio.new_event_loop()
            # Start the loop on a background thread
            _loop_thread = threading.Thread(
                target=_run_loop_forever,
                args=(_worker_loop,),
                daemon=True,
                name="pyworkflow-event-loop",
            )
            _loop_thread.start()


def close_worker_loop() -> None:
    """
    Close the persistent event loop for this worker process.

    Called from worker_shutdown signal handler.
    """
    global _worker_loop, _loop_thread

    with _loop_lock:
        if _worker_loop is not None and not _worker_loop.is_closed():
            try:
                # Schedule shutdown on the loop thread
                _worker_loop.call_soon_threadsafe(_worker_loop.stop)
                if _loop_thread is not None:
                    _loop_thread.join(timeout=5.0)
            except Exception:
                pass
            finally:
                # Close the loop after it has stopped
                if not _worker_loop.is_closed():
                    _worker_loop.close()
                _worker_loop = None
                _loop_thread = None


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """
    Get the persistent event loop for this worker process.

    If no loop exists (e.g., running outside Celery worker), creates one
    with a background thread.

    Returns:
        The worker's event loop
    """
    global _worker_loop, _loop_thread

    with _loop_lock:
        if _worker_loop is None or _worker_loop.is_closed():
            # Not in a Celery worker or loop was closed - create a new one
            _worker_loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(
                target=_run_loop_forever,
                args=(_worker_loop,),
                daemon=True,
                name="pyworkflow-event-loop",
            )
            _loop_thread.start()
        return _worker_loop


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """
    Run a coroutine on the persistent worker event loop.

    This is a drop-in replacement for asyncio.run() that reuses
    the same event loop across tasks, allowing connection pools
    to be shared.

    Thread-safe: can be called from any thread (prefork, threads pool, etc.).
    The coroutine is submitted to the background event loop thread via
    asyncio.run_coroutine_threadsafe().

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
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


def is_loop_running() -> bool:
    """Check if the worker loop exists and is not closed."""
    return _worker_loop is not None and not _worker_loop.is_closed()
