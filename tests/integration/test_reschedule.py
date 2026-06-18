"""
Integration tests for SIGTERM task rescheduling against a REAL Redis.

These exercise the actual pieces the unit tests fake out:
- the per-pod in-flight registry hash in real Redis,
- real singleton-lock release + re-acquire,
- a real broker publish (apply_async lands a message on the queue's Redis list).

Requires a Redis at localhost:6379. Skipped otherwise. Uses a dedicated db (14)
which is flushed around each test, so it never touches app data on db 0.
"""

import pytest

from pyworkflow.celery import reschedule

try:
    import redis as _redis

    _client = _redis.from_url("redis://localhost:6379/0")
    _client.ping()
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not available"),
]

TEST_DB_URL = "redis://localhost:6379/14"
STEPS_QUEUE = "pyworkflow.steps"


@pytest.fixture
def env(monkeypatch):
    """Real Redis-backed reschedule wiring on an isolated db, fixed pod id."""
    from pyworkflow.celery.app import create_celery_app
    from pyworkflow.celery.singleton import RedisLockBackend, SingletonWorkflowTask

    raw = _redis.from_url(TEST_DB_URL, decode_responses=True)
    raw.flushdb()

    monkeypatch.delenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", raising=False)
    monkeypatch.setenv("HOSTNAME", "itest-pod")

    app = create_celery_app(broker_url=TEST_DB_URL, result_backend=TEST_DB_URL)

    @app.task(
        base=SingletonWorkflowTask,
        name="test.reschedule_probe",
        queue=STEPS_QUEUE,
        unique_on=["run_id"],
    )
    def probe(run_id, payload=None):  # pragma: no cover - never executed (no worker)
        return None

    backend = RedisLockBackend(TEST_DB_URL)
    monkeypatch.setattr(reschedule, "_get_backend", lambda: backend)
    monkeypatch.setattr(reschedule, "_resolve_task", lambda name: app.tasks.get(name))

    registry_key = "pyworkflow:inflight:itest-pod"

    yield {
        "raw": raw,
        "app": app,
        "probe": probe,
        "backend": backend,
        "registry_key": registry_key,
    }

    raw.flushdb()


def test_track_writes_and_clears_real_hash(env):
    probe, raw, key = env["probe"], env["raw"], env["registry_key"]

    reschedule.track_task_start(probe, "tid-1", (), {"run_id": "rX"})
    entries = raw.hgetall(key)
    assert "tid-1" in entries
    assert "test.reschedule_probe" in entries["tid-1"]  # descriptor carries task name

    reschedule.track_task_end("tid-1")
    assert raw.hgetall(key) == {}


def test_reschedule_releases_lock_and_reenqueues(env):
    probe, raw, key = env["probe"], env["raw"], env["registry_key"]

    # Simulate the running task holding its singleton lock.
    lock_key = probe.generate_lock("test.reschedule_probe", [], {"run_id": "rX"})
    assert probe.acquire_lock(lock_key, "tid-1") is True
    assert raw.get(lock_key) == "tid-1"

    reschedule.track_task_start(probe, "tid-1", (), {"run_id": "rX"})
    llen_before = raw.llen(STEPS_QUEUE)

    reschedule.reschedule_inflight_on_shutdown()

    # A fresh copy was published to the real broker queue...
    assert raw.llen(STEPS_QUEUE) == llen_before + 1
    # ...and it re-acquired the singleton lock under a NEW task id (so the dying
    # task's lock no longer blocks it).
    holder = raw.get(lock_key)
    assert holder is not None and holder != "tid-1"
    # Registry drained.
    assert raw.hgetall(key) == {}


def test_direct_apply_async_is_deduped_without_release(env):
    """Documents WHY reschedule must release the lock first: a plain re-enqueue
    while the lock is held is silently deduped and never reaches the broker."""
    probe, raw = env["probe"], env["raw"]

    lock_key = probe.generate_lock("test.reschedule_probe", [], {"run_id": "rX"})
    assert probe.acquire_lock(lock_key, "tid-1") is True
    llen_before = raw.llen(STEPS_QUEUE)

    probe.apply_async(kwargs={"run_id": "rX"})  # no release -> singleton dedup

    assert raw.llen(STEPS_QUEUE) == llen_before  # nothing enqueued
    assert raw.get(lock_key) == "tid-1"  # lock untouched


def test_disabled_writes_nothing(env, monkeypatch):
    monkeypatch.setenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", "0")
    probe, raw, key = env["probe"], env["raw"], env["registry_key"]

    reschedule.track_task_start(probe, "tid-1", (), {"run_id": "rX"})
    reschedule.reschedule_inflight_on_shutdown()

    assert raw.hgetall(key) == {}
    assert raw.llen(STEPS_QUEUE) == 0
