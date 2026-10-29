"""
Hand in-flight tasks off to another worker when a worker is shut down (SIGTERM).

When a Celery worker pod is reclaimed (e.g. an AWS spot node drain), it receives
SIGTERM. Celery's default *warm* shutdown waits for running tasks to finish, and
if the pod is SIGKILLed first, the task's message (``task_acks_late=True``) stays
unacked until the Redis ``visibility_timeout`` (an hour by default). The parent
workflow stays SUSPENDED that whole time, so the user-facing flow silently hangs.

How the handoff works
---------------------
SIGTERM runs Celery's *cold* shutdown with a *soft* phase first (Celery >= 5.5):

1. Soft phase: the worker waits ``worker_soft_shutdown_timeout`` seconds, so a
   task that finishes in time acks normally and nothing is handed off.
2. Cold phase: Celery cancels the task consumer, terminates the pool processes
   still running a task, and closes the broker connection. Kombu restores the
   unacked messages to their queues, and a live worker picks them up within
   seconds.

Each in-flight message goes back to the queue exactly once, and only after the
process that was running it is dead.

Why not re-enqueue at the start of shutdown (#733)
--------------------------------------------------
The previous design re-published every in-flight task as soon as the consumer
stopped. Warm shutdown then let the original keep running, and closing the
consumer connection made kombu restore the original message too, so every
in-flight task ran three times at once: the original plus two copies. The
completion checks in the tasks can't prevent that, because nothing is completed
while all three are still running.

Celery does the same thing when ``REMAP_SIGTERM=SIGQUIT`` is set, but billiard
reads that variable at import time, which is too early to rely on for every way
a worker can be launched. So we install the handler ourselves once the worker is
ready; when ``REMAP_SIGTERM`` is set, Celery already handles SIGTERM and we
leave it alone. Only the prefork pool is supported: terminating a running task
requires a separate process.

The timeout must be lower than the orchestrator's grace period (Kubernetes
``terminationGracePeriodSeconds``, 30s by default). A SIGKILL during the soft
phase leaves the message unacked until the ``visibility_timeout`` again.

Gates:
- ``PYWORKFLOW_RESCHEDULE_ON_SIGTERM`` (default on; set to ``0``/``false``/``no``
  to fall back to Celery's plain warm shutdown).
- ``PYWORKFLOW_SOFT_SHUTDOWN_TIMEOUT`` (seconds, default 20). ``0`` hands tasks
  off immediately without waiting for them.
"""

import os
import threading
from typing import Any

from loguru import logger

DEFAULT_SOFT_SHUTDOWN_TIMEOUT = 20.0


def _enabled() -> bool:
    return os.getenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def soft_shutdown_timeout() -> float:
    """Seconds a SIGTERMed worker waits for running tasks before handing them off."""
    raw = os.getenv("PYWORKFLOW_SOFT_SHUTDOWN_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_SOFT_SHUTDOWN_TIMEOUT
    try:
        return max(float(raw), 0.0)
    except ValueError:
        logger.warning(
            f"reschedule: invalid PYWORKFLOW_SOFT_SHUTDOWN_TIMEOUT={raw!r}, "
            f"using {DEFAULT_SOFT_SHUTDOWN_TIMEOUT}s"
        )
        return DEFAULT_SOFT_SHUTDOWN_TIMEOUT


def soft_shutdown_config() -> dict[str, Any]:
    """Celery settings for the SIGTERM handoff (empty when disabled)."""
    if not _enabled():
        return {}
    return {"worker_soft_shutdown_timeout": soft_shutdown_timeout()}


def _is_worker_stopping() -> bool:
    """True once the worker has started shutting down (warm or cold)."""
    try:
        from celery.worker import state

        # Identity checks (matching celery.worker.state): the flags are set to the
        # exit code, which can be 0 (EX_OK) -- `0 == False`.
        def _set(v: Any) -> bool:
            return v is not None and v is not False

        return _set(state.should_stop) or _set(state.should_terminate)
    except Exception:
        return False


def _is_prefork(worker: Any) -> bool:
    from celery.concurrency.prefork import TaskPool

    return isinstance(getattr(worker, "pool", None), TaskPool)


def _on_sigterm(worker: Any) -> None:
    """Run Celery's soft + cold shutdown, as it does for ``REMAP_SIGTERM=SIGQUIT``."""
    from celery.apps import worker as celery_worker

    # A second SIGTERM must not start a second soft wait: treat it like a repeated
    # SIGQUIT (cancel the tasks now, keep waiting for the cold shutdown).
    celery_worker.install_worker_term_hard_handler(
        worker, sig="SIGTERM", callback=celery_worker.during_soft_shutdown
    )
    logger.warning(
        "reschedule: SIGTERM received, handing off in-flight tasks after "
        f"{worker.app.conf.worker_soft_shutdown_timeout}s"
    )
    celery_worker.on_cold_shutdown(worker)


def install_sigterm_handoff(worker: Any) -> bool:
    """
    Make SIGTERM hand in-flight tasks off via Celery's soft + cold shutdown.

    Called once the worker is ready (after Celery installed its own signal
    handlers). Returns True if the handler was installed. Never raises.
    """
    if not _enabled() or worker is None or _is_worker_stopping():
        return False
    try:
        from celery.apps import worker as celery_worker

        if not all(hasattr(celery_worker, n) for n in ("on_cold_shutdown", "during_soft_shutdown")):
            logger.warning(
                "reschedule: SIGTERM handoff needs Celery >= 5.5 (soft shutdown), "
                "keeping Celery's warm shutdown"
            )
            return False
        if getattr(celery_worker, "REMAP_SIGTERM", None):
            return False  # Celery already maps SIGTERM to the cold shutdown.
        if not _is_prefork(worker):
            logger.info("reschedule: SIGTERM handoff requires the prefork pool, skipping")
            return False
        if threading.current_thread() is not threading.main_thread():
            logger.warning("reschedule: not on the main thread, cannot install SIGTERM handler")
            return False

        celery_worker.install_worker_term_hard_handler(worker, sig="SIGTERM", callback=_on_sigterm)
        return True
    except Exception as exc:
        logger.warning(f"reschedule: failed to install SIGTERM handoff: {exc}")
        return False
