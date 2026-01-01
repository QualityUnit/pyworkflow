"""
Unit tests for SingletonWorkflowTask and related functionality.
"""

from unittest.mock import MagicMock, patch

import pytest

from pyworkflow.celery.singleton import (
    DuplicateTaskError,
    RedisLockBackend,
    SingletonConfig,
    SingletonWorkflowTask,
    generate_lock_key,
)


class TestGenerateLockKey:
    """Test the generate_lock_key function."""

    def test_basic_lock_key(self):
        """Test basic lock key generation."""
        key = generate_lock_key("my_task", ["arg1", "arg2"], {"key": "value"})

        # Should have the prefix
        assert key.startswith("pyworkflow:lock:")

        # Should be deterministic
        key2 = generate_lock_key("my_task", ["arg1", "arg2"], {"key": "value"})
        assert key == key2

    def test_custom_prefix(self):
        """Test lock key with custom prefix."""
        key = generate_lock_key("my_task", [], {}, key_prefix="custom:prefix:")
        assert key.startswith("custom:prefix:")

    def test_different_args_different_keys(self):
        """Test that different arguments produce different keys."""
        key1 = generate_lock_key("my_task", ["arg1"], {})
        key2 = generate_lock_key("my_task", ["arg2"], {})
        assert key1 != key2

    def test_different_kwargs_different_keys(self):
        """Test that different kwargs produce different keys."""
        key1 = generate_lock_key("my_task", [], {"a": 1})
        key2 = generate_lock_key("my_task", [], {"a": 2})
        assert key1 != key2

    def test_different_tasks_different_keys(self):
        """Test that different task names produce different keys."""
        key1 = generate_lock_key("task_a", ["arg"], {})
        key2 = generate_lock_key("task_b", ["arg"], {})
        assert key1 != key2

    def test_empty_args_and_kwargs(self):
        """Test with empty arguments."""
        key = generate_lock_key("my_task", None, None)
        assert key.startswith("pyworkflow:lock:")

    def test_non_json_serializable_args(self):
        """Test that non-JSON-serializable args are handled via default=str."""

        class CustomObj:
            def __str__(self):
                return "custom_object"

        key = generate_lock_key("my_task", [CustomObj()], {})
        assert key.startswith("pyworkflow:lock:")

    def test_kwargs_order_independent(self):
        """Test that kwargs order doesn't affect the key (sort_keys=True)."""
        key1 = generate_lock_key("my_task", [], {"a": 1, "b": 2})
        key2 = generate_lock_key("my_task", [], {"b": 2, "a": 1})
        assert key1 == key2


class TestSingletonConfig:
    """Test SingletonConfig class."""

    def test_config_defaults(self):
        """Test default configuration values."""
        mock_app = MagicMock()
        mock_app.conf.get.return_value = None

        config = SingletonConfig(mock_app)

        # Test that it returns None for backend_url when not configured
        assert config.backend_url is None

    def test_config_with_values(self):
        """Test configuration with custom values."""
        mock_app = MagicMock()
        mock_app.conf.get.side_effect = lambda key, default=None: {
            "singleton_backend_url": "redis://localhost:6379/0",
            "singleton_key_prefix": "test:lock:",
            "singleton_lock_expiry": 7200,
            "singleton_raise_on_duplicate": True,
        }.get(key, default)

        config = SingletonConfig(mock_app)

        assert config.backend_url == "redis://localhost:6379/0"
        assert config.key_prefix == "test:lock:"
        assert config.lock_expiry == 7200
        assert config.raise_on_duplicate is True


class TestRedisLockBackend:
    """Test RedisLockBackend class with mocked Redis."""

    def test_lock_success(self):
        """Test successful lock acquisition."""
        with patch("redis.from_url") as mock_from_url:
            mock_redis = MagicMock()
            mock_redis.set.return_value = True
            mock_from_url.return_value = mock_redis

            backend = RedisLockBackend("redis://localhost:6379/0")
            result = backend.lock("test_key", "task_123", expiry=3600)

            assert result is True
            mock_redis.set.assert_called_once_with("test_key", "task_123", nx=True, ex=3600)

    def test_lock_failure(self):
        """Test failed lock acquisition (already locked)."""
        with patch("redis.from_url") as mock_from_url:
            mock_redis = MagicMock()
            mock_redis.set.return_value = None  # Redis returns None when NX fails
            mock_from_url.return_value = mock_redis

            backend = RedisLockBackend("redis://localhost:6379/0")
            result = backend.lock("test_key", "task_123", expiry=3600)

            assert result is False

    def test_unlock(self):
        """Test lock release."""
        with patch("redis.from_url") as mock_from_url:
            mock_redis = MagicMock()
            mock_from_url.return_value = mock_redis

            backend = RedisLockBackend("redis://localhost:6379/0")
            backend.unlock("test_key")

            mock_redis.delete.assert_called_once_with("test_key")

    def test_get(self):
        """Test getting lock value."""
        with patch("redis.from_url") as mock_from_url:
            mock_redis = MagicMock()
            mock_redis.get.return_value = "task_123"
            mock_from_url.return_value = mock_redis

            backend = RedisLockBackend("redis://localhost:6379/0")
            result = backend.get("test_key")

            assert result == "task_123"
            mock_redis.get.assert_called_once_with("test_key")


class TestDuplicateTaskError:
    """Test DuplicateTaskError exception."""

    def test_error_creation(self):
        """Test creating DuplicateTaskError."""
        error = DuplicateTaskError("Duplicate task found", "task_123")

        assert error.task_id == "task_123"
        assert "Duplicate task found" in str(error)


class TestSingletonWorkflowTask:
    """Test SingletonWorkflowTask class."""

    @pytest.fixture
    def mock_celery_app(self):
        """Create a mock Celery app."""
        app = MagicMock()
        app.conf.get.side_effect = lambda key, default=None: {
            "singleton_backend_url": None,
            "singleton_key_prefix": "pyworkflow:lock:",
            "singleton_lock_expiry": 3600,
            "singleton_raise_on_duplicate": False,
            "broker_url": "redis://localhost:6379/0",
        }.get(key, default)
        app.conf.broker_url = "redis://localhost:6379/0"
        return app

    @pytest.fixture
    def task_class(self, mock_celery_app):
        """Create a test task class."""

        class TestTask(SingletonWorkflowTask):
            name = "test_task"
            unique_on = ["run_id", "step_id"]

            def run(self, run_id: str, step_id: str, data: dict | None = None):
                return {"run_id": run_id, "step_id": step_id}

        task = TestTask()
        task.bind(mock_celery_app)
        return task

    def test_generate_lock_with_unique_on(self, task_class):
        """Test lock generation with unique_on."""
        lock_key = task_class.generate_lock(
            "test_task",
            task_args=["run_123", "step_456"],
            task_kwargs={"data": {"extra": "value"}},
        )

        # Should use only run_id and step_id for the lock
        expected_args = ["run_123", "step_456"]
        expected_key = generate_lock_key(
            "test_task", expected_args, {}, key_prefix="pyworkflow:lock:"
        )
        assert lock_key == expected_key

    def test_generate_lock_with_string_unique_on(self, mock_celery_app):
        """Test lock generation with single string unique_on."""

        class SingleArgTask(SingletonWorkflowTask):
            name = "single_arg_task"
            unique_on = "run_id"  # Single string instead of list

            def run(self, run_id: str, other_data: str = ""):
                return run_id

        task = SingleArgTask()
        task.bind(mock_celery_app)

        lock_key = task.generate_lock(
            "single_arg_task",
            task_args=["run_123"],
            task_kwargs={"other_data": "ignored"},
        )

        expected_key = generate_lock_key(
            "single_arg_task", ["run_123"], {}, key_prefix="pyworkflow:lock:"
        )
        assert lock_key == expected_key

    def test_generate_lock_nested_dict_access(self, mock_celery_app):
        """Test lock generation with nested dict access in unique_on."""

        class NestedTask(SingletonWorkflowTask):
            name = "nested_task"
            unique_on = ["data.run_id"]

            def run(self, data: dict):
                return data

        task = NestedTask()
        task.bind(mock_celery_app)

        lock_key = task.generate_lock(
            "nested_task",
            task_args=[{"run_id": "nested_run_123", "other": "value"}],
            task_kwargs={},
        )

        expected_key = generate_lock_key(
            "nested_task", ["nested_run_123"], {}, key_prefix="pyworkflow:lock:"
        )
        assert lock_key == expected_key

    def test_generate_lock_no_unique_on(self, mock_celery_app):
        """Test lock generation without unique_on (uses all args)."""

        class AllArgsTask(SingletonWorkflowTask):
            name = "all_args_task"
            unique_on = None  # Use all args

            def run(self, arg1: str, arg2: str):
                return arg1 + arg2

        task = AllArgsTask()
        task.bind(mock_celery_app)

        lock_key = task.generate_lock(
            "all_args_task",
            task_args=["value1", "value2"],
            task_kwargs={},
        )

        expected_key = generate_lock_key(
            "all_args_task", ["value1", "value2"], {}, key_prefix="pyworkflow:lock:"
        )
        assert lock_key == expected_key

    def test_generate_lock_missing_key_raises_error(self, mock_celery_app):
        """Test that missing unique_on key raises ValueError."""

        class MissingKeyTask(SingletonWorkflowTask):
            name = "missing_key_task"
            unique_on = ["nonexistent_arg"]

            def run(self, real_arg: str):
                return real_arg

        task = MissingKeyTask()
        task.bind(mock_celery_app)

        with pytest.raises(ValueError, match="not found in task arguments"):
            task.generate_lock("missing_key_task", task_args=["value"], task_kwargs={})

    def test_acquire_lock_no_backend(self, mock_celery_app):
        """Test acquire_lock returns True when no backend available."""

        class NoBackendTask(SingletonWorkflowTask):
            name = "no_backend_task"

            def run(self):
                return "done"

        task = NoBackendTask()
        task.bind(mock_celery_app)
        # Set backend to None to simulate no Redis
        task._singleton_backend = None

        # Override singleton_backend property to return None
        with patch.object(
            NoBackendTask, "singleton_backend", new_callable=lambda: property(lambda _: None)
        ):
            task2 = NoBackendTask()
            task2.bind(mock_celery_app)
            result = task2.acquire_lock("test_key", "task_123")
            assert result is True

    def test_release_lock_no_backend(self, mock_celery_app):
        """Test release_lock does nothing when no backend available."""

        class NoBackendTask(SingletonWorkflowTask):
            name = "no_backend_task"

            def run(self):
                return "done"

        task = NoBackendTask()
        task.bind(mock_celery_app)

        # Override singleton_backend property to return None
        with patch.object(
            NoBackendTask, "singleton_backend", new_callable=lambda: property(lambda _: None)
        ):
            task2 = NoBackendTask()
            task2.bind(mock_celery_app)
            # Should not raise even with no backend
            task2.release_lock(task_args=[], task_kwargs={})

    def test_lock_expiry_from_task_attribute(self, mock_celery_app):
        """Test that per-task lock_expiry overrides config."""

        class CustomExpiryTask(SingletonWorkflowTask):
            name = "custom_expiry_task"
            lock_expiry = 7200  # 2 hours

            def run(self):
                return "done"

        task = CustomExpiryTask()
        task.bind(mock_celery_app)

        assert task._lock_expiry == 7200

    def test_raise_on_duplicate_from_task_attribute(self, mock_celery_app):
        """Test that per-task raise_on_duplicate overrides config."""

        class RaiseOnDuplicateTask(SingletonWorkflowTask):
            name = "raise_task"
            raise_on_duplicate = True

            def run(self):
                return "done"

        task = RaiseOnDuplicateTask()
        task.bind(mock_celery_app)

        assert task._raise_on_duplicate is True


class TestSingletonWorkflowTaskApplyAsync:
    """Test apply_async behavior of SingletonWorkflowTask."""

    @pytest.fixture
    def mock_celery_app(self):
        """Create a mock Celery app."""
        app = MagicMock()
        app.conf.get.side_effect = lambda key, default=None: {
            "singleton_backend_url": "redis://localhost:6379/0",
            "singleton_key_prefix": "pyworkflow:lock:",
            "singleton_lock_expiry": 3600,
            "singleton_raise_on_duplicate": False,
        }.get(key, default)
        app.conf.broker_url = "redis://localhost:6379/0"
        return app

    def test_apply_async_acquires_lock(self, mock_celery_app):
        """Test that apply_async acquires lock before submitting."""

        class LockingTask(SingletonWorkflowTask):
            name = "locking_task"
            unique_on = ["task_id"]

            def run(self, task_id: str):
                return task_id

        task = LockingTask()
        task.bind(mock_celery_app)

        mock_backend = MagicMock()
        mock_backend.lock.return_value = True
        task._singleton_backend = mock_backend

        # Verify acquire_lock works through the backend
        result = task.acquire_lock("test_key", "task_123")
        assert result is True
        mock_backend.lock.assert_called_once()

    def test_apply_async_returns_existing_on_duplicate(self, mock_celery_app):
        """Test that apply_async returns existing result when lock fails."""

        class DuplicateTask(SingletonWorkflowTask):
            name = "duplicate_task"
            unique_on = ["task_id"]

            def run(self, task_id: str):
                return task_id

        task = DuplicateTask()
        task.bind(mock_celery_app)

        mock_backend = MagicMock()
        mock_backend.lock.return_value = False  # Lock acquisition fails
        mock_backend.get.return_value = "existing_task_456"
        task._singleton_backend = mock_backend

        # Mock AsyncResult
        mock_async_result = MagicMock()
        task.AsyncResult = MagicMock(return_value=mock_async_result)

        # Call apply_async
        result = task.apply_async(args=["my_task_id"], kwargs={})

        # Should return the existing task's AsyncResult
        assert result == mock_async_result
        task.AsyncResult.assert_called_once_with("existing_task_456")

    def test_apply_async_raises_on_duplicate_when_configured(self, mock_celery_app):
        """Test that apply_async raises DuplicateTaskError when configured."""

        class RaisingTask(SingletonWorkflowTask):
            name = "raising_task"
            unique_on = ["task_id"]
            raise_on_duplicate = True

            def run(self, task_id: str):
                return task_id

        task = RaisingTask()
        task.bind(mock_celery_app)

        mock_backend = MagicMock()
        mock_backend.lock.return_value = False
        mock_backend.get.return_value = "existing_task_456"
        task._singleton_backend = mock_backend

        with pytest.raises(DuplicateTaskError) as exc_info:
            task.apply_async(args=["my_task_id"], kwargs={})

        assert exc_info.value.task_id == "existing_task_456"

    def test_apply_async_no_backend_proceeds_normally(self):
        """Test that apply_async proceeds normally when no backend."""
        # Create app with non-Redis broker (no backend will be created)
        mock_app = MagicMock()
        mock_app.conf.get.side_effect = lambda key, default=None: {
            "singleton_backend_url": None,
            "singleton_key_prefix": "pyworkflow:lock:",
            "singleton_lock_expiry": 3600,
            "singleton_raise_on_duplicate": False,
        }.get(key, default)
        mock_app.conf.broker_url = "amqp://guest:guest@localhost:5672//"  # Non-Redis broker

        class NoBackendTask(SingletonWorkflowTask):
            name = "no_backend_task"
            unique_on = ["task_id"]

            def run(self, task_id: str):
                return task_id

        task = NoBackendTask()
        task.bind(mock_app)

        # Verify no backend is created for non-Redis broker
        assert task.singleton_backend is None

        # Should call parent apply_async
        with patch.object(
            SingletonWorkflowTask.__bases__[0], "apply_async", return_value=MagicMock()
        ) as mock_super:
            task.apply_async(args=["my_task_id"], kwargs={})
            # Parent should be called
            mock_super.assert_called_once()


class TestSingletonWorkflowTaskCallbacks:
    """Test on_success and on_failure callbacks."""

    @pytest.fixture
    def mock_celery_app(self):
        """Create a mock Celery app."""
        app = MagicMock()
        app.conf.get.side_effect = lambda key, default=None: {
            "singleton_backend_url": "redis://localhost:6379/0",
            "singleton_key_prefix": "pyworkflow:lock:",
            "singleton_lock_expiry": 3600,
            "singleton_raise_on_duplicate": False,
        }.get(key, default)
        app.conf.broker_url = "redis://localhost:6379/0"
        return app

    def test_on_success_releases_lock(self, mock_celery_app):
        """Test that on_success releases the lock."""

        class SuccessTask(SingletonWorkflowTask):
            name = "success_task"
            unique_on = ["task_id"]
            release_lock_on_success = True

            def run(self, task_id: str):
                return task_id

        task = SuccessTask()
        task.bind(mock_celery_app)

        mock_backend = MagicMock()
        task._singleton_backend = mock_backend

        task.on_success(
            retval="result",
            task_id="celery_task_123",
            args=("my_task_id",),
            kwargs={},
        )

        # Lock should be released
        mock_backend.unlock.assert_called_once()

    def test_on_success_no_release_when_disabled(self, mock_celery_app):
        """Test that on_success doesn't release lock when disabled."""

        class NoReleaseTask(SingletonWorkflowTask):
            name = "no_release_task"
            unique_on = ["task_id"]
            release_lock_on_success = False

            def run(self, task_id: str):
                return task_id

        task = NoReleaseTask()
        task.bind(mock_celery_app)

        mock_backend = MagicMock()
        task._singleton_backend = mock_backend

        task.on_success(
            retval="result",
            task_id="celery_task_123",
            args=("my_task_id",),
            kwargs={},
        )

        # Lock should NOT be released
        mock_backend.unlock.assert_not_called()

    def test_on_failure_keeps_lock_for_retry(self, mock_celery_app):
        """Test that on_failure keeps lock when retries remain."""

        class RetryTask(SingletonWorkflowTask):
            name = "retry_task"
            unique_on = ["task_id"]
            max_retries = 3
            release_lock_on_failure = False

            def run(self, task_id: str):
                return task_id

        task = RetryTask()
        task.bind(mock_celery_app)

        mock_backend = MagicMock()
        task._singleton_backend = mock_backend

        # Mock request with retries < max using Celery's request stack
        mock_request = MagicMock()
        mock_request.retries = 1
        task.request_stack.push(mock_request)

        try:
            task.on_failure(
                exc=Exception("test error"),
                task_id="celery_task_123",
                args=("my_task_id",),
                kwargs={},
                einfo=None,
            )
        finally:
            task.request_stack.pop()

        # Lock should NOT be released (retries remaining)
        mock_backend.unlock.assert_not_called()

    def test_on_failure_releases_lock_after_max_retries(self, mock_celery_app):
        """Test that on_failure releases lock when max retries exceeded."""

        class MaxRetryTask(SingletonWorkflowTask):
            name = "max_retry_task"
            unique_on = ["task_id"]
            max_retries = 3
            release_lock_on_failure = False

            def run(self, task_id: str):
                return task_id

        task = MaxRetryTask()
        task.bind(mock_celery_app)

        mock_backend = MagicMock()
        task._singleton_backend = mock_backend

        # Mock request with retries >= max using Celery's request stack
        mock_request = MagicMock()
        mock_request.retries = 3
        task.request_stack.push(mock_request)

        try:
            task.on_failure(
                exc=Exception("test error"),
                task_id="celery_task_123",
                args=("my_task_id",),
                kwargs={},
                einfo=None,
            )
        finally:
            task.request_stack.pop()

        # Lock should be released (max retries exceeded)
        mock_backend.unlock.assert_called_once()

    def test_on_failure_always_releases_when_configured(self, mock_celery_app):
        """Test that on_failure releases lock when release_lock_on_failure=True."""

        class AlwaysReleaseTask(SingletonWorkflowTask):
            name = "always_release_task"
            unique_on = ["task_id"]
            max_retries = 3
            release_lock_on_failure = True

            def run(self, task_id: str):
                return task_id

        task = AlwaysReleaseTask()
        task.bind(mock_celery_app)

        mock_backend = MagicMock()
        task._singleton_backend = mock_backend

        # Mock request with retries < max using Celery's request stack
        mock_request = MagicMock()
        mock_request.retries = 0
        task.request_stack.push(mock_request)

        try:
            task.on_failure(
                exc=Exception("test error"),
                task_id="celery_task_123",
                args=("my_task_id",),
                kwargs={},
                einfo=None,
            )
        finally:
            task.request_stack.pop()

        # Lock should be released (release_lock_on_failure=True)
        mock_backend.unlock.assert_called_once()
