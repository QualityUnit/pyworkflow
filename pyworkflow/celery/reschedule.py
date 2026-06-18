"""
Reschedule in-flight tasks when a worker is shut down (SIGTERM).

When a Celery worker pod is reclaimed (e.g. an AWS spot node drain), it receives
SIGTERM and warm-shuts-down. Any step task that was executing is *not* promptly
redelivered: with ``task_acks_late=True`` the broker only re-queues it after the
Redis ``visibility_timeout`` (an hour by default), and the parent workflow stays
SUSPENDED that whole time -- so the user-facing flow silently hangs with no output.

This module makes the worker re-enqueue its in-flight task(s) *immediately* on
shutdown so a live worker resumes them within seconds instead of ~1h.

Why a shared Redis registry (not process-local state)
-----------------------------------------------------
Tasks execute in forked **child** processes, but the shutdown hook runs in the
**main** process. The main process can't see a child's in-memory task args, so
children publish what they are running to a per-pod Redis hash
(``pyworkflow:inflight:<pod>``) on ``task_prerun`` and remove it on
``task_postrun``. On shutdown the main process reads that hash and re-enqueues
every entry.

Why a consumer bootstep (event-based, no sleep)
-----------------------------------------------
The re-enqueue must happen *after* this worker's broker consumer is cancelled --
otherwise the worker's own still-active consumer grabs the message straight back
into ``unacked`` (stranded until the visibility_timeout). There is no Celery
*signal* for "consumer cancelled" (``worker_shutting_down`` fires before it;
``worker_shutdown`` fires after the pool has drained the long task -- far too
late). So we hook the consumer blueprint directly with a bootstep that
``requires`` the ``Tasks`` step: its ``stop()`` runs as the consumer is torn
down (early in shutdown, before the pool drain). There we cancel the task
consumer ourselves -- guaranteeing this worker stops fetching -- and only then
re-enqueue, so the message lands in the *ready* queue and another worker's
blocking BRPOP picks it up immediately. Event-based, deterministic, no sleep.

Safety against double execution
-------------------------------
``execute_step_task`` short-circuits on an existing ``STEP_COMPLETED`` event (and
on a terminal run status), and ``_record_step_completion_and_resume`` re-checks
before recording, so at most one completion is ever recorded no matter how many
copies run. Only ``SingletonWorkflowTask`` tasks that declare ``unique_on`` are
rescheduled -- those are idempotent by run_id/step_id. Tasks without a uniqueness
key are left alone.

Gate: ``PYWORKFLOW_RESCHEDULE_ON_SIGTERM`` (default on; set to ``0``/``false``/``no``
to disable and fall back to the old visibility_timeout redelivery behaviour).
"""

import json
import os
import socket
import threading
from typing import Any

from celery import bootsteps
from loguru import logger

# Registry hash self-expires so a hard-killed pod (no postrun) cannot leak entries.
_REGISTRY_TTL_SECONDS = 6 * 3600
_REGISTRY_KEY_PREFIX = "pyworkflow:inflight:"

_backend_lock = threading.Lock()
_backend: Any = None
_backend_resolved = False


def _enabled() -> bool:
    return os.getenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _pod_id() -> str:
    """Stable per-pod id shared by the main process and its forked children."""
    return os.environ.get("HOSTNAME") or socket.gethostname()


def _registry_key() -> str:
    return f"{_REGISTRY_KEY_PREFIX}{_pod_id()}"


def _get_backend() -> Any:
    """
    Cached sentinel-aware Redis backend, reusing the singleton lock configuration
    (same broker/sentinel the task locks already use). Returns None when no Redis
    backend is configured, in which case rescheduling is a no-op.
    """
    global _backend, _backend_resolved
    if _backend_resolved:
        return _backend
    with _backend_lock:
        if _backend_resolved:
            return _backend
        try:
            from pyworkflow.celery.app import celery_app
            from pyworkflow.celery.singleton import RedisLockBackend, SingletonConfig

            cfg = SingletonConfig(celery_app)
            url = cfg.backend_url
            if url:
                _backend = RedisLockBackend(
                    url,
                    is_sentinel=cfg.is_sentinel,
                    sentinel_master=cfg.sentinel_master,
                )
        except Exception as exc:
            logger.warning(f"reschedule: could not initialise redis backend: {exc}")
            _backend = None
        _backend_resolved = True
    return _backend


def _resolve_task(name: str) -> Any:
    """Look up a registered task instance by name (used to re-enqueue)."""
    from pyworkflow.celery.app import celery_app

    return celery_app.tasks.get(name)


def _resolve_queue(task: Any) -> str | None:
    """Best-effort queue the task was delivered on, so the re-enqueue lands there."""
    try:
        delivery_info = getattr(task.request, "delivery_info", None) or {}
        routing_key = delivery_info.get("routing_key")
        if routing_key:
            return routing_key
    except Exception:
        pass
    return getattr(task, "queue", None)


def track_task_start(
    task: Any,
    task_id: str | None,
    args: Any,
    kwargs: Any,
) -> None:
    """Publish a task as in-flight (per pod) so it can be re-enqueued on SIGTERM."""
    if not _enabled() or task is None or task_id is None:
        return

    # Import here to avoid import cycles at module load.
    from pyworkflow.celery.singleton import SingletonWorkflowTask

    # Only re-enqueue tasks keyed by a uniqueness field (run_id/step_id). These are
    # idempotent; blindly re-enqueuing a non-unique task could start duplicate runs.
    if not isinstance(task, SingletonWorkflowTask) or not task.unique_on:
        return

    backend = _get_backend()
    if backend is None:
        return

    descriptor = json.dumps(
        {
            "name": task.name,
            "args": list(args or ()),
            "kwargs": dict(kwargs or {}),
            "queue": _resolve_queue(task),
        },
        default=str,
    )
    key = _registry_key()
    try:
        backend._execute_with_refresh(lambda: backend.redis.hset(key, task_id, descriptor))
        backend._execute_with_refresh(lambda: backend.redis.expire(key, _REGISTRY_TTL_SECONDS))
    except Exception as exc:
        logger.warning(f"reschedule: failed to record in-flight task {task_id}: {exc}")


def track_task_end(task_id: str | None) -> None:
    """Remove a task from the in-flight registry once it has finished."""
    if not _enabled() or task_id is None:
        return
    backend = _get_backend()
    if backend is None:
        return
    try:
        backend._execute_with_refresh(lambda: backend.redis.hdel(_registry_key(), task_id))
    except Exception as exc:
        logger.warning(f"reschedule: failed to clear in-flight task {task_id}: {exc}")


def reschedule_inflight_on_shutdown() -> None:
    """
    Re-enqueue every task still recorded as in-flight for this pod. Assumes the
    caller has already cancelled this worker's task consumer (see
    :class:`RescheduleConsumerStep`) so the fresh copy is not re-grabbed. Never
    raises -- shutdown must not be blocked.
    """
    if not _enabled():
        return
    backend = _get_backend()
    if backend is None:
        return

    key = _registry_key()
    try:
        entries = backend._execute_with_refresh(lambda: backend.redis.hgetall(key)) or {}
    except Exception as exc:
        logger.warning(f"reschedule: failed to read in-flight registry: {exc}")
        return

    if not entries:
        return

    for task_id, raw in entries.items():
        try:
            descriptor = json.loads(raw)
            task = _resolve_task(descriptor["name"])
            if task is None:
                logger.warning(
                    f"reschedule: unknown task {descriptor.get('name')!r}, "
                    f"cannot re-enqueue {task_id}"
                )
                continue

            args = descriptor.get("args") or []
            kwargs = descriptor.get("kwargs") or {}
            queue = descriptor.get("queue")

            # Release the singleton lock held by the dying task so the re-enqueued
            # copy is not rejected as a duplicate. release_lock() regenerates the
            # exact lock key from the same args/kwargs the running task holds.
            try:
                task.release_lock(task_args=list(args), task_kwargs=kwargs)
            except Exception as exc:
                logger.warning(
                    f"reschedule: failed to release lock for {task.name} "
                    f"(old_task_id={task_id}): {exc}"
                )

            options = {"queue": queue} if queue else {}
            task.apply_async(args=list(args), kwargs=kwargs, **options)
            logger.warning(
                f"reschedule: re-enqueued in-flight task on shutdown "
                f"task={task.name} old_task_id={task_id} queue={queue}"
            )
        except Exception as exc:
            logger.opt(exception=True).error(
                f"reschedule: failed to re-enqueue task {task_id}: {exc}"
            )

    # Drop the registry for this pod; a fresh worker starts with a clean slate.
    try:
        backend._execute_with_refresh(lambda: backend.redis.delete(key))
    except Exception as exc:
        logger.warning(f"reschedule: failed to clear in-flight registry: {exc}")


def _is_worker_stopping() -> bool:
    """
    True only when the worker is actually shutting down (SIGTERM warm or cold),
    not on a transient consumer restart (e.g. broker reconnect), which also tears
    the consumer down. Celery's SIGTERM handler sets these flags before the
    consumer is stopped.
    """
    try:
        from celery.worker import state

        # Identity checks (matching celery.worker.state): the flags are set to the
        # exit code, which can be 0 (EX_OK) -- `0 == False`, so membership/equality
        # against False would wrongly treat a clean exitcode-0 shutdown as "not
        # stopping" and skip the reschedule.
        def _set(v: Any) -> bool:
            return v is not None and v is not False

        return _set(state.should_stop) or _set(state.should_terminate)
    except Exception:
        return False


def on_consumer_stop(consumer: Any) -> None:
    """
    Invoked from the consumer bootstep as the consumer is torn down. Cancels this
    worker's task consumer (so it stops fetching) and re-enqueues in-flight work.
    """
    if not _enabled() or not _is_worker_stopping():
        return

    # Cancel our own task consumer first: once we stop BRPOPing, the re-enqueued
    # message stays in the ready list for another worker instead of being grabbed
    # back here into `unacked`. Tasks.stop() will cancel again later (idempotent).
    task_consumer = getattr(consumer, "task_consumer", None)
    if task_consumer is not None:
        try:
            task_consumer.cancel()
        except Exception as exc:
            logger.warning(f"reschedule: failed to cancel task consumer: {exc}")

    # Cancelling is not enough on the Redis transport: a BRPOP this worker already
    # issued is accepted by the server and will still pop the *next* message pushed
    # to those queues -- including the copy we are about to re-enqueue. The dying
    # worker then exits before recording it in `unacked`, so the message is lost
    # entirely (neither in the ready list nor restorable via visibility_timeout).
    # Drop the consumer's broker connection so any in-flight BRPOP is aborted
    # server-side *before* we re-publish; the re-enqueue itself uses the producer
    # pool (a separate connection), so it is unaffected.
    _abort_consumer_fetching(consumer)

    reschedule_inflight_on_shutdown()


def _abort_consumer_fetching(consumer: Any) -> None:
    """Close the consumer's broker connection to abort any in-flight BRPOP."""
    conn = getattr(consumer, "connection", None)
    if conn is None:
        return
    try:
        # collect() tears down channels + the underlying socket, aborting the
        # pending BRPOP. Never raises into shutdown.
        conn.collect()
    except Exception as exc:
        logger.warning(f"reschedule: failed to drop consumer connection: {exc}")


class RescheduleConsumerStep(bootsteps.StartStopStep):
    """
    Consumer bootstep that re-enqueues this worker's in-flight tasks the moment
    the consumer is torn down on shutdown -- event-based, no polling/sleep.

    ``requires`` the task consumer (``Tasks``) so that (a) ``c.task_consumer``
    exists when our ``stop()`` runs and (b) we run *before* ``Tasks.stop()``,
    letting us cancel the consumer ourselves and re-enqueue while it's guaranteed
    not fetching.
    """

    requires = ("celery.worker.consumer:Tasks",)

    def start(self, c: Any) -> None:  # noqa: D401 - nothing to start
        pass

    def stop(self, c: Any) -> None:
        try:
            on_consumer_stop(c)
        except Exception as exc:  # never block consumer teardown
            logger.warning(f"reschedule: consumer-stop hook failed: {exc}")
