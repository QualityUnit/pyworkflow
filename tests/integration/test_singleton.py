"""
Integration tests for SingletonWorkflowTask with real Redis.

These tests require a running Redis instance at localhost:6379.
Skip if Redis is not available.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock, patch

import pytest

# Check if Redis is available
try:
    import redis

    _redis_client = redis.from_url("redis://localhost:6379/0")
    _redis_client.ping()
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False


pytestmark = pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not available")


from pyworkflow.celery.singleton import (
    DuplicateTaskError,
    RedisLockBackend,
    SingletonWorkflowTask,
)


@pytest.fixture
def redis_backend():
    """Create a Redis backend and clean up after test."""
    backend = RedisLockBackend("redis://localhost:6379/0")
    yield backend
    # Clean up any test locks
    backend.redis.delete("pyworkflow:lock:*")


@pytest.fixture
def clean_redis():
    """Clean up test keys before and after each test."""
    client = redis.from_url("redis://localhost:6379/0")

    # Clean before
    for key in client.scan_iter("pyworkflow:test:*"):
        client.delete(key)

    yield client

    # Clean after
    for key in client.scan_iter("pyworkflow:test:*"):
        client.delete(key)


class TestRedisLockBackendIntegration:
    """Integration tests for RedisLockBackend with real Redis."""

    def test_lock_and_unlock(self, clean_redis):
        """Test basic lock acquisition and release."""
        backend = RedisLockBackend("redis://localhost:6379/0")
        lock_key = "pyworkflow:test:lock_test_1"

        # Acquire lock
        result = backend.lock(lock_key, "task_123", expiry=60)
        assert result is True

        # Verify lock exists
        assert backend.get(lock_key) == "task_123"

        # Release lock
        backend.unlock(lock_key)

        # Verify lock is gone
        assert backend.get(lock_key) is None

    def test_lock_prevents_duplicate(self, clean_redis):
        """Test that a lock prevents another task from acquiring it."""
        backend = RedisLockBackend("redis://localhost:6379/0")
        lock_key = "pyworkflow:test:lock_test_2"

        # First lock acquisition should succeed
        result1 = backend.lock(lock_key, "task_1", expiry=60)
        assert result1 is True

        # Second lock acquisition should fail
        result2 = backend.lock(lock_key, "task_2", expiry=60)
        assert result2 is False

        # First task ID should still be in the lock
        assert backend.get(lock_key) == "task_1"

        # Clean up
        backend.unlock(lock_key)

    def test_lock_expiry(self, clean_redis):
        """Test that lock expires after TTL."""
        backend = RedisLockBackend("redis://localhost:6379/0")
        lock_key = "pyworkflow:test:lock_expiry"

        # Acquire lock with 1 second expiry
        result = backend.lock(lock_key, "task_123", expiry=1)
        assert result is True
        assert backend.get(lock_key) == "task_123"

        # Wait for expiry
        time.sleep(1.5)

        # Lock should be gone
        assert backend.get(lock_key) is None

        # Should be able to acquire again
        result2 = backend.lock(lock_key, "task_456", expiry=60)
        assert result2 is True

        # Clean up
        backend.unlock(lock_key)

    def test_concurrent_lock_acquisition(self, clean_redis):
        """Test that only one of multiple concurrent lock attempts succeeds."""
        backend = RedisLockBackend("redis://localhost:6379/0")
        lock_key = "pyworkflow:test:concurrent_lock"
        results = []
        start_event = Event()

        def try_lock(task_id):
            start_event.wait()  # Wait for all threads to be ready
            result = backend.lock(lock_key, task_id, expiry=60)
            results.append((task_id, result))

        # Start multiple threads trying to acquire the lock simultaneously
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(try_lock, f"task_{i}") for i in range(5)]

            # Start all threads at once
            start_event.set()

            # Wait for all to complete
            for f in futures:
                f.result()

        # Exactly one should have succeeded
        successful = [r for r in results if r[1] is True]
        assert len(successful) == 1

        # The others should have failed
        failed = [r for r in results if r[1] is False]
        assert len(failed) == 4

        # Clean up
        backend.unlock(lock_key)


class TestSingletonWorkflowTaskIntegration:
    """Integration tests for SingletonWorkflowTask with real Redis."""

    @pytest.fixture
    def mock_celery_app(self):
        """Create a mock Celery app configured for Redis."""
        app = MagicMock()
        app.conf.get.side_effect = lambda key, default=None: {
            "singleton_backend_url": "redis://localhost:6379/0",
            "singleton_key_prefix": "pyworkflow:test:",
            "singleton_lock_expiry": 60,
            "singleton_raise_on_duplicate": False,
        }.get(key, default)
        app.conf.broker_url = "redis://localhost:6379/0"
        app.backend = MagicMock()
        app.backend.generate_task_id.return_value = "generated_task_id"
        return app

    def test_task_lock_lifecycle(self, mock_celery_app, clean_redis):
        """Test full lock lifecycle: acquire on apply, release on success."""

        class LifecycleTask(SingletonWorkflowTask):
            name = "lifecycle_task"
            unique_on = ["task_id"]

            def run(self, task_id: str):
                return f"completed_{task_id}"

        task = LifecycleTask()
        task.bind(mock_celery_app)

        # Reset backend to use test prefix
        task._singleton_backend = None
        task._singleton_config = None

        # Generate lock key
        lock_key = task.generate_lock("lifecycle_task", ["test_123"], {})

        # Verify lock doesn't exist initially
        backend = task.singleton_backend
        assert backend.get(lock_key) is None

        # Acquire lock manually (simulating apply_async)
        acquired = task.acquire_lock(lock_key, "celery_task_id_1")
        assert acquired is True

        # Verify lock exists
        assert backend.get(lock_key) == "celery_task_id_1"

        # Simulate success callback
        task.on_success(
            retval="result",
            task_id="celery_task_id_1",
            args=("test_123",),
            kwargs={},
        )

        # Lock should be released
        assert backend.get(lock_key) is None

    def test_duplicate_task_blocked(self, mock_celery_app, clean_redis):
        """Test that duplicate tasks are blocked when lock is held."""

        class BlockedTask(SingletonWorkflowTask):
            name = "blocked_task"
            unique_on = ["run_id"]

            def run(self, run_id: str):
                return run_id

        task = BlockedTask()
        task.bind(mock_celery_app)
        task._singleton_backend = None
        task._singleton_config = None

        backend = task.singleton_backend
        lock_key = task.generate_lock("blocked_task", ["run_123"], {})

        # Manually hold the lock (simulating a running task)
        backend.lock(lock_key, "existing_task_456", expiry=60)

        # Mock AsyncResult
        mock_async_result = MagicMock()
        task.AsyncResult = MagicMock(return_value=mock_async_result)

        # Try to apply_async - should return existing task's result
        result = task.apply_async(args=["run_123"], kwargs={})

        # Should return the existing task's AsyncResult
        assert result == mock_async_result
        task.AsyncResult.assert_called_with("existing_task_456")

        # Clean up
        backend.unlock(lock_key)

    def test_duplicate_task_raises_when_configured(self, mock_celery_app, clean_redis):
        """Test that duplicate tasks raise error when configured."""

        class RaisingTask(SingletonWorkflowTask):
            name = "raising_task"
            unique_on = ["run_id"]
            raise_on_duplicate = True

            def run(self, run_id: str):
                return run_id

        task = RaisingTask()
        task.bind(mock_celery_app)
        task._singleton_backend = None
        task._singleton_config = None

        backend = task.singleton_backend
        lock_key = task.generate_lock("raising_task", ["run_456"], {})

        # Manually hold the lock
        backend.lock(lock_key, "existing_task_789", expiry=60)

        # Try to apply_async - should raise
        with pytest.raises(DuplicateTaskError) as exc_info:
            task.apply_async(args=["run_456"], kwargs={})

        assert exc_info.value.task_id == "existing_task_789"

        # Clean up
        backend.unlock(lock_key)

    def test_lock_released_on_apply_async_failure(self, mock_celery_app, clean_redis):
        """Test that lock is released if apply_async fails."""

        class FailingApplyTask(SingletonWorkflowTask):
            name = "failing_apply_task"
            unique_on = ["task_id"]

            def run(self, task_id: str):
                return task_id

        task = FailingApplyTask()
        task.bind(mock_celery_app)
        task._singleton_backend = None
        task._singleton_config = None

        backend = task.singleton_backend
        lock_key = task.generate_lock("failing_apply_task", ["test_id"], {})

        # Make parent's apply_async raise
        with (
            patch.object(
                SingletonWorkflowTask.__bases__[0],
                "apply_async",
                side_effect=Exception("Connection failed"),
            ),
            pytest.raises(Exception, match="Connection failed"),
        ):
            task.apply_async(args=["test_id"], kwargs={})

        # Lock should be released after failure
        assert backend.get(lock_key) is None

    def test_on_failure_lock_behavior(self, mock_celery_app, clean_redis):
        """Test that on_failure keeps lock when retries remain, releases on max retries."""

        class RetryingTask(SingletonWorkflowTask):
            name = "retrying_task"
            unique_on = ["task_id"]
            max_retries = 5
            release_lock_on_failure = False

            def run(self, task_id: str):
                return task_id

        task = RetryingTask()
        task.bind(mock_celery_app)
        task._singleton_backend = None
        task._singleton_config = None

        backend = task.singleton_backend
        lock_key = task.generate_lock("retrying_task", ["retry_test"], {})

        # Acquire lock manually
        backend.lock(lock_key, "task_id_123", expiry=60)

        # Simulate failure with retries remaining using Celery's request stack
        mock_request = MagicMock()
        mock_request.retries = 2  # Less than max_retries
        task.request_stack.push(mock_request)

        try:
            task.on_failure(
                exc=Exception("temporary error"),
                task_id="task_id_123",
                args=("retry_test",),
                kwargs={},
                einfo=None,
            )

            # Lock should still be held (on_failure doesn't release when retries remain)
            assert backend.get(lock_key) == "task_id_123"

            # Simulate final failure (max retries exceeded)
            task.request_stack.pop()
            mock_request.retries = 5
            task.request_stack.push(mock_request)

            task.on_failure(
                exc=Exception("final error"),
                task_id="task_id_123",
                args=("retry_test",),
                kwargs={},
                einfo=None,
            )

            # Lock should now be released
            assert backend.get(lock_key) is None
        finally:
            task.request_stack.pop()

    def test_on_retry_releases_lock(self, mock_celery_app, clean_redis):
        """Test that on_retry releases lock so retry can acquire it via apply_async."""

        class RetryingTask(SingletonWorkflowTask):
            name = "retrying_task_on_retry"
            unique_on = ["task_id"]
            max_retries = 5

            def run(self, task_id: str):
                return task_id

        task = RetryingTask()
        task.bind(mock_celery_app)
        task._singleton_backend = None
        task._singleton_config = None

        backend = task.singleton_backend
        lock_key = task.generate_lock("retrying_task_on_retry", ["retry_test"], {})

        # Acquire lock manually
        backend.lock(lock_key, "task_id_456", expiry=60)

        # Simulate retry using Celery's request stack
        mock_request = MagicMock()
        mock_request.retries = 1
        task.request_stack.push(mock_request)

        try:
            task.on_retry(
                exc=Exception("temporary error"),
                task_id="task_id_456",
                args=("retry_test",),
                kwargs={},
                einfo=None,
            )

            # Lock should be released so retry can acquire it
            assert backend.get(lock_key) is None
        finally:
            task.request_stack.pop()


class TestSingletonConcurrency:
    """Test singleton behavior under concurrent access."""

    @pytest.fixture
    def mock_celery_app(self):
        """Create a mock Celery app configured for Redis."""
        app = MagicMock()
        app.conf.get.side_effect = lambda key, default=None: {
            "singleton_backend_url": "redis://localhost:6379/0",
            "singleton_key_prefix": "pyworkflow:test:",
            "singleton_lock_expiry": 60,
            "singleton_raise_on_duplicate": False,
        }.get(key, default)
        app.conf.broker_url = "redis://localhost:6379/0"
        app.backend = MagicMock()
        app.backend.generate_task_id.side_effect = lambda: f"task_{time.time_ns()}"
        return app

    def test_concurrent_apply_async_only_one_proceeds(self, mock_celery_app, clean_redis):
        """Test that concurrent apply_async calls result in only one task running."""

        class ConcurrentTask(SingletonWorkflowTask):
            name = "concurrent_task"
            unique_on = ["run_id"]

            def run(self, run_id: str):
                return run_id

        results = []
        start_event = Event()

        def try_apply(run_id, index):
            task = ConcurrentTask()
            task.bind(mock_celery_app)
            task._singleton_backend = None
            task._singleton_config = None

            # Mock AsyncResult to track duplicates
            task.AsyncResult = MagicMock(return_value=MagicMock(id=f"existing_{index}"))

            def mock_apply(*args, **kwargs):
                result = MagicMock()
                result.id = f"new_{index}"
                return result

            start_event.wait()

            with patch.object(
                SingletonWorkflowTask.__bases__[0], "apply_async", side_effect=mock_apply
            ):
                try:
                    result = task.apply_async(args=[run_id], kwargs={})
                    if hasattr(result, "id") and result.id.startswith("new_"):
                        results.append(("new", index))
                    else:
                        results.append(("existing", index))
                except Exception as e:
                    results.append(("error", str(e)))

        # Start multiple threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(try_apply, "shared_run_id", i) for i in range(5)]
            start_event.set()
            for f in futures:
                f.result()

        # Only one should have gotten "new", others should get "existing"
        new_tasks = [r for r in results if r[0] == "new"]
        existing_tasks = [r for r in results if r[0] == "existing"]

        assert len(new_tasks) == 1, f"Expected 1 new task, got {len(new_tasks)}: {results}"
        assert len(existing_tasks) == 4, (
            f"Expected 4 existing, got {len(existing_tasks)}: {results}"
        )
