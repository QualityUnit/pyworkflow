"""
Unit tests for re-enqueueing in-flight tasks on worker shutdown (SIGTERM).

See pyworkflow/celery/reschedule.py. The in-flight registry lives in Redis (a
per-pod hash) so the main process can read what the child processes are running;
here we substitute a tiny in-memory fake for that Redis.
"""

from unittest.mock import MagicMock

import pytest

from pyworkflow.celery import reschedule
from pyworkflow.celery.singleton import SingletonWorkflowTask


class _FakeRedis:
    """Minimal hash-only fake supporting the ops reschedule.py uses."""

    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value
        return 1

    def hdel(self, key, field):
        return self.hashes.get(key, {}).pop(field, None) is not None

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def expire(self, key, ttl):
        return True

    def delete(self, key):
        self.hashes.pop(key, None)
        return 1


class _FakeBackend:
    """Stands in for RedisLockBackend (passthrough _execute_with_refresh + .redis)."""

    def __init__(self):
        self.redis = _FakeRedis()

    def _execute_with_refresh(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def _make_singleton_task(
    name: str = "pyworkflow.execute_step",
    unique_on=("run_id", "step_id"),
    queue: str | None = "pyworkflow.steps",
    routing_key: str | None = "pyworkflow.steps",
):
    """A MagicMock that passes ``isinstance(_, SingletonWorkflowTask)``."""
    task = MagicMock(spec=SingletonWorkflowTask)
    task.name = name
    task.unique_on = list(unique_on) if unique_on else unique_on
    task.queue = queue
    task.request.delivery_info = {"routing_key": routing_key} if routing_key else {}
    return task


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    """Force the feature on, give it a fake Redis, and a name->task resolver."""
    monkeypatch.delenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", raising=False)
    monkeypatch.setenv("HOSTNAME", "test-pod-0")

    backend = _FakeBackend()
    monkeypatch.setattr(reschedule, "_get_backend", lambda: backend)

    # Re-enqueue resolves tasks by name; map names to the mocks the test created.
    registry: dict[str, MagicMock] = {}
    monkeypatch.setattr(reschedule, "_resolve_task", lambda name: registry.get(name))

    backend.registry = registry  # let tests register name -> task
    return backend


def _track(backend, task, task_id, kwargs):
    """Register the task for name-resolution and record it as in-flight."""
    backend.registry[task.name] = task
    reschedule.track_task_start(task, task_id, (), kwargs)


class TestTracking:
    def test_singleton_task_is_tracked(self, fake_backend):
        task = _make_singleton_task()
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})
        assert fake_backend.redis.hashes["pyworkflow:inflight:test-pod-0"]

    def test_non_singleton_task_is_ignored(self, fake_backend):
        task = MagicMock()  # not a SingletonWorkflowTask
        reschedule.track_task_start(task, "task-1", (), {"run_id": "r1"})
        assert fake_backend.redis.hashes == {}

    def test_singleton_without_unique_on_is_ignored(self, fake_backend):
        task = _make_singleton_task(unique_on=None)
        reschedule.track_task_start(task, "task-1", (), {"run_id": "r1"})
        assert fake_backend.redis.hashes == {}

    def test_track_end_clears_entry(self, fake_backend):
        task = _make_singleton_task()
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})
        reschedule.track_task_end("task-1")
        assert fake_backend.redis.hgetall("pyworkflow:inflight:test-pod-0") == {}

    def test_none_task_id_is_ignored(self, fake_backend):
        task = _make_singleton_task()
        reschedule.track_task_start(task, None, (), {"run_id": "r1", "step_id": "s1"})
        assert fake_backend.redis.hashes == {}


class TestReschedule:
    def test_reenqueues_inflight_task(self, fake_backend):
        task = _make_singleton_task()
        kwargs = {"run_id": "r1", "step_id": "s1", "args_json": "[]"}
        _track(fake_backend, task, "task-1", kwargs)

        reschedule.reschedule_inflight_on_shutdown()

        # Lock released with the captured args/kwargs so the fresh copy isn't deduped.
        task.release_lock.assert_called_once_with(task_args=[], task_kwargs=kwargs)
        # Re-enqueued exactly once, back onto the original queue.
        task.apply_async.assert_called_once()
        _, call_kwargs = task.apply_async.call_args
        assert call_kwargs["queue"] == "pyworkflow.steps"
        assert call_kwargs["kwargs"] == kwargs
        # Registry drained so a later shutdown call is a no-op.
        assert fake_backend.redis.hgetall("pyworkflow:inflight:test-pod-0") == {}

    def test_clean_completion_is_not_reenqueued(self, fake_backend):
        task = _make_singleton_task()
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})
        reschedule.track_task_end("task-1")  # task finished normally

        reschedule.reschedule_inflight_on_shutdown()

        task.apply_async.assert_not_called()

    def test_queue_falls_back_to_task_queue(self, fake_backend):
        task = _make_singleton_task(routing_key=None, queue="pyworkflow.schedules")
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})

        reschedule.reschedule_inflight_on_shutdown()

        _, call_kwargs = task.apply_async.call_args
        assert call_kwargs["queue"] == "pyworkflow.schedules"

    def test_handler_swallows_apply_async_errors(self, fake_backend):
        task = _make_singleton_task()
        task.apply_async.side_effect = RuntimeError("broker down")
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})

        # Must never raise out of the shutdown path.
        reschedule.reschedule_inflight_on_shutdown()

    def test_release_lock_failure_does_not_block_reenqueue(self, fake_backend):
        task = _make_singleton_task()
        task.release_lock.side_effect = RuntimeError("redis down")
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})

        reschedule.reschedule_inflight_on_shutdown()

        task.apply_async.assert_called_once()

    def test_unknown_task_name_is_skipped(self, fake_backend):
        task = _make_singleton_task(name="pyworkflow.execute_step")
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})
        # Simulate the task no longer being registered at shutdown time.
        fake_backend.registry.clear()

        # Should not raise even though the name can't be resolved.
        reschedule.reschedule_inflight_on_shutdown()
        task.apply_async.assert_not_called()

    def test_multiple_inflight_tasks_all_reenqueued(self, fake_backend):
        t1 = _make_singleton_task(name="pyworkflow.execute_step")
        t2 = _make_singleton_task(
            name="pyworkflow.resume_workflow",
            queue="pyworkflow.schedules",
            routing_key="pyworkflow.schedules",
        )
        _track(fake_backend, t1, "task-1", {"run_id": "r1", "step_id": "s1"})
        _track(fake_backend, t2, "task-2", {"run_id": "r2", "step_id": "s2"})

        reschedule.reschedule_inflight_on_shutdown()

        t1.apply_async.assert_called_once()
        t2.apply_async.assert_called_once()


class TestNoBackend:
    def test_no_redis_backend_is_noop(self, monkeypatch):
        monkeypatch.setattr(reschedule, "_get_backend", lambda: None)
        task = _make_singleton_task()
        # Tracking and reschedule both degrade to no-ops without raising.
        reschedule.track_task_start(task, "task-1", (), {"run_id": "r1", "step_id": "s1"})
        reschedule.reschedule_inflight_on_shutdown()
        task.apply_async.assert_not_called()


class TestDisabled:
    def test_disabled_skips_tracking(self, fake_backend, monkeypatch):
        monkeypatch.setenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", "0")
        task = _make_singleton_task()
        reschedule.track_task_start(task, "task-1", (), {"run_id": "r1", "step_id": "s1"})
        assert fake_backend.redis.hashes == {}

    @pytest.mark.parametrize("value", ["false", "no", "0", "FALSE", "No"])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", value)
        assert reschedule._enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", ""])
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", value)
        assert reschedule._enabled() is True

    def test_disabled_reschedule_is_noop(self, fake_backend, monkeypatch):
        task = _make_singleton_task()
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})
        monkeypatch.setenv("PYWORKFLOW_RESCHEDULE_ON_SIGTERM", "0")

        reschedule.reschedule_inflight_on_shutdown()

        task.apply_async.assert_not_called()


@pytest.fixture
def _stopping(monkeypatch):
    """Simulate the worker being in SIGTERM shutdown (state.should_stop set)."""
    from celery.worker import state

    monkeypatch.setattr(state, "should_stop", 0, raising=False)
    monkeypatch.setattr(state, "should_terminate", None, raising=False)


class TestConsumerStopHook:
    """
    Drives the prerun tracking signal + the consumer bootstep teardown hook
    (on_consumer_stop), which is the real event-based path on shutdown.
    """

    def test_prerun_then_consumer_stop_roundtrip(self, fake_backend, _stopping):
        from pyworkflow.celery import app as app_module

        task = _make_singleton_task()
        fake_backend.registry[task.name] = task
        kwargs = {"run_id": "r1", "step_id": "s1"}

        app_module.on_task_prerun(task_id="task-1", task=task, args=(), kwargs=kwargs)
        assert fake_backend.redis.hgetall("pyworkflow:inflight:test-pod-0")

        consumer = MagicMock()  # has .task_consumer.cancel()
        reschedule.on_consumer_stop(consumer)

        consumer.task_consumer.cancel.assert_called_once()  # stop fetching first
        task.apply_async.assert_called_once()  # then re-enqueue

    def test_consumer_connection_dropped_before_reenqueue(self, fake_backend, _stopping):
        # Cancelling the consumer is not enough on Redis: a BRPOP this worker
        # already issued can still grab the re-enqueued copy and lose it on exit.
        # The connection must be dropped (aborting the in-flight BRPOP) *before*
        # the message is re-published.
        task = _make_singleton_task()
        fake_backend.registry[task.name] = task
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})

        order = []
        consumer = MagicMock()
        consumer.connection.collect.side_effect = lambda *_, **__: order.append("collect")
        task.apply_async.side_effect = lambda *_, **__: order.append("apply_async")

        reschedule.on_consumer_stop(consumer)

        consumer.connection.collect.assert_called_once()
        assert order == [
            "collect",
            "apply_async",
        ], "connection must be dropped before the task is re-enqueued"

    def test_consumer_stop_is_noop_when_not_shutting_down(self, fake_backend, monkeypatch):
        # Transient consumer restart (e.g. broker reconnect): flags are clear.
        from celery.worker import state

        monkeypatch.setattr(state, "should_stop", None, raising=False)
        monkeypatch.setattr(state, "should_terminate", None, raising=False)

        task = _make_singleton_task()
        _track(fake_backend, task, "task-1", {"run_id": "r1", "step_id": "s1"})

        consumer = MagicMock()
        reschedule.on_consumer_stop(consumer)

        consumer.task_consumer.cancel.assert_not_called()
        task.apply_async.assert_not_called()

    def test_postrun_clears_before_consumer_stop(self, fake_backend, _stopping):
        from pyworkflow.celery import app as app_module

        task = _make_singleton_task()
        fake_backend.registry[task.name] = task
        app_module.on_task_prerun(
            task_id="task-1", task=task, args=(), kwargs={"run_id": "r1", "step_id": "s1"}
        )
        app_module.on_task_postrun(task_id="task-1")
        reschedule.on_consumer_stop(MagicMock())
        task.apply_async.assert_not_called()

    def test_bootstep_requires_tasks_and_delegates(self, fake_backend, _stopping, monkeypatch):
        # The bootstep must run after the Tasks consumer step exists.
        assert "celery.worker.consumer:Tasks" in reschedule.RescheduleConsumerStep.requires
        # And its stop() delegates to on_consumer_stop.
        called = {}
        monkeypatch.setattr(reschedule, "on_consumer_stop", lambda c: called.setdefault("c", c))
        step = object.__new__(reschedule.RescheduleConsumerStep)  # skip Step.__init__
        sentinel = MagicMock()
        step.stop(sentinel)
        assert called.get("c") is sentinel
