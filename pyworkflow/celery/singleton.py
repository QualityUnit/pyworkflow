"""
Singleton task implementation for PyWorkflow.

Provides Redis-based distributed locking to prevent duplicate task execution.
Self-contained implementation (no external dependencies beyond redis).

Based on:
- steinitzu/celery-singleton library concepts
- FlowHunt's battle-tested refinements for retry-safe lock management
"""

import inspect
import json
from hashlib import md5
from typing import Any
from uuid import uuid4

from celery import Task
from celery.exceptions import WorkerLostError
from loguru import logger


def generate_lock_key(
    task_name: str,
    task_args: list[Any] | tuple[Any, ...] | None = None,
    task_kwargs: dict[str, Any] | None = None,
    key_prefix: str = "pyworkflow:lock:",
) -> str:
    """
    Generate a unique lock key for a task based on its name and arguments.

    Uses MD5 hash to keep key length reasonable while ensuring uniqueness.
    """
    str_args = json.dumps(task_args or [], sort_keys=True, default=str)
    str_kwargs = json.dumps(task_kwargs or {}, sort_keys=True, default=str)
    task_hash = md5((task_name + str_args + str_kwargs).encode()).hexdigest()
    return key_prefix + task_hash


class SingletonConfig:
    """Configuration for singleton task behavior."""

    def __init__(self, app: Any):
        self.app = app

    @property
    def backend_url(self) -> str | None:
        return self.app.conf.get("singleton_backend_url")

    @property
    def key_prefix(self) -> str:
        return self.app.conf.get("singleton_key_prefix", "pyworkflow:lock:")

    @property
    def lock_expiry(self) -> int:
        return self.app.conf.get("singleton_lock_expiry", 3600)

    @property
    def raise_on_duplicate(self) -> bool:
        return self.app.conf.get("singleton_raise_on_duplicate", False)


class RedisLockBackend:
    """Redis backend for distributed locking."""

    def __init__(self, url: str):
        import redis

        self.redis = redis.from_url(url, decode_responses=True)

    def lock(self, lock_key: str, task_id: str, expiry: int | None = None) -> bool:
        """Acquire lock atomically. Returns True if acquired."""
        return bool(self.redis.set(lock_key, task_id, nx=True, ex=expiry))

    def unlock(self, lock_key: str) -> None:
        """Release the lock."""
        self.redis.delete(lock_key)

    def get(self, lock_key: str) -> str | None:
        """Get the task ID holding the lock."""
        return self.redis.get(lock_key)


class DuplicateTaskError(Exception):
    """Raised when attempting to queue a duplicate singleton task."""

    def __init__(self, message: str, task_id: str):
        self.task_id = task_id
        super().__init__(message)


class SingletonWorkflowTask(Task):
    """
    Base class for singleton workflow tasks with distributed locking.

    Features:
    - Redis-based lock prevents duplicate execution
    - Support for unique_on with nested dict/list access (e.g., "data.run_id")
    - Retry-safe: lock released in on_retry callback to allow retry to acquire it
    - Lock released on success or when max retries exceeded
    - Time-based lock expiry as safety net

    Configuration:
        unique_on: List of argument names to use for uniqueness (e.g., ["run_id", "step_id"])
                   Supports nested access with dot notation (e.g., ["data.run_id"])
        raise_on_duplicate: If True, raise DuplicateTaskError instead of returning existing result
        lock_expiry: Lock TTL in seconds (default: 3600 = 1 hour)

    Example:
        @celery_app.task(
            base=SingletonWorkflowTask,
            unique_on=["run_id", "step_id"],
        )
        def my_task(run_id: str, step_id: str, data: dict):
            ...
    """

    abstract = True

    # Singleton configuration (can be overridden per-task)
    unique_on: list[str] | str | None = None
    raise_on_duplicate: bool | None = None
    lock_expiry: int | None = None

    # Lock behavior
    release_lock_on_success: bool = True
    release_lock_on_failure: bool = False  # Only release on max retries exceeded

    # Celery task settings
    max_retries: int | None = None
    acks_on_failure_or_timeout: bool = True

    # Cached instances (class-level, shared across task instances)
    _singleton_backend: RedisLockBackend | None = None
    _singleton_config: SingletonConfig | None = None

    @property
    def singleton_config(self) -> SingletonConfig:
        if self._singleton_config is None:
            self._singleton_config = SingletonConfig(self.app)
        return self._singleton_config

    @property
    def singleton_backend(self) -> RedisLockBackend | None:
        if self._singleton_backend is None:
            url = self.singleton_config.backend_url
            if not url:
                # Try broker URL if it's Redis
                broker = self.app.conf.broker_url or ""
                if broker.startswith("redis://") or broker.startswith("rediss://"):
                    url = broker
            if url:
                self._singleton_backend = RedisLockBackend(url)
        return self._singleton_backend

    @property
    def _lock_expiry(self) -> int:
        if self.lock_expiry is not None:
            return self.lock_expiry
        return self.singleton_config.lock_expiry

    @property
    def _raise_on_duplicate(self) -> bool:
        if self.raise_on_duplicate is not None:
            return self.raise_on_duplicate
        return self.singleton_config.raise_on_duplicate

    def generate_lock(
        self,
        task_name: str,
        task_args: list[Any] | tuple[Any, ...] | None = None,
        task_kwargs: dict[str, Any] | None = None,
    ) -> str:
        """Generate lock key, supporting nested attribute access via unique_on."""
        unique_on = self.unique_on
        task_args = task_args or []
        task_kwargs = task_kwargs or {}

        if unique_on:
            if isinstance(unique_on, str):
                unique_on = [unique_on]

            # Bind arguments to function signature
            sig = inspect.signature(self.run)
            bound = sig.bind(*task_args, **task_kwargs).arguments

            unique_args: list[Any] = []
            for key in unique_on:
                keys = key.split(".")
                if keys[0] not in bound:
                    raise ValueError(f"Key '{keys[0]}' not found in task arguments")

                value = bound[keys[0]]
                # Navigate nested structure (supports one level of nesting)
                if len(keys) == 2:
                    nested_key = keys[1]
                    if isinstance(value, dict):
                        if nested_key not in value:
                            raise ValueError(f"Key '{nested_key}' not found in dict")
                        unique_args.append(value[nested_key])
                    elif isinstance(value, (list, tuple)):
                        unique_args.append(value[int(nested_key)])
                    elif hasattr(value, nested_key):
                        unique_args.append(getattr(value, nested_key))
                    else:
                        raise ValueError(f"Key '{key}' has unsupported type")
                elif len(keys) == 1:
                    unique_args.append(value)
                else:
                    raise ValueError(f"Key '{key}' has too many levels (max 2)")

            return generate_lock_key(
                task_name,
                unique_args,
                {},
                key_prefix=self.singleton_config.key_prefix,
            )
        else:
            return generate_lock_key(
                task_name,
                list(task_args),
                task_kwargs,
                key_prefix=self.singleton_config.key_prefix,
            )

    def acquire_lock(self, lock_key: str, task_id: str) -> bool:
        """Attempt to acquire lock. Returns True if successful."""
        backend = self.singleton_backend
        if backend is None:
            return True  # No Redis = no locking
        return backend.lock(lock_key, task_id, expiry=self._lock_expiry)

    def release_lock(
        self,
        task_args: list[Any] | tuple[Any, ...] | None = None,
        task_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Release the lock for this task."""
        backend = self.singleton_backend
        if backend is None:
            return
        lock_key = self.generate_lock(self.name, task_args, task_kwargs)
        backend.unlock(lock_key)

    def get_existing_task_id(self, lock_key: str) -> str | None:
        """Get task ID holding the lock, if any."""
        backend = self.singleton_backend
        if backend is None:
            return None
        return backend.get(lock_key)

    def apply_async(
        self,
        args: list[Any] | tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        task_id: str | None = None,
        **options: Any,
    ) -> Any:
        """Override apply_async to implement singleton behavior."""
        args = args or []
        kwargs = kwargs or {}
        task_id = task_id or str(uuid4())

        backend = self.singleton_backend
        if backend is None:
            # No Redis = normal behavior
            return super().apply_async(args, kwargs, task_id=task_id, **options)

        lock_key = self.generate_lock(self.name, args, kwargs)

        # Try to acquire lock and run
        if self.acquire_lock(lock_key, task_id):
            try:
                return super().apply_async(args, kwargs, task_id=task_id, **options)
            except Exception:
                # Release lock if apply_async fails
                backend.unlock(lock_key)
                raise

        # Lock not acquired - check for existing task
        existing_task_id = self.get_existing_task_id(lock_key)
        if existing_task_id:
            logger.debug(
                "Singleton: duplicate task blocked",
                task=self.name,
                existing_task_id=existing_task_id,
            )
            if self._raise_on_duplicate:
                raise DuplicateTaskError(f"Duplicate of task {existing_task_id}", existing_task_id)
            return self.AsyncResult(existing_task_id)

        # Race condition: lock disappeared, retry
        if self.acquire_lock(lock_key, task_id):
            try:
                return super().apply_async(args, kwargs, task_id=task_id, **options)
            except Exception:
                backend.unlock(lock_key)
                raise

        # Still can't acquire - return existing or submit anyway
        existing_task_id = self.get_existing_task_id(lock_key)
        if existing_task_id:
            return self.AsyncResult(existing_task_id)

        # Fallback: submit anyway (rare edge case)
        logger.warning(f"Singleton lock unstable, submitting anyway: {self.name}")
        return super().apply_async(args, kwargs, task_id=task_id, **options)

    def on_success(
        self, retval: Any, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        """Release lock on successful task completion."""
        if self.release_lock_on_success:
            self.release_lock(task_args=args, task_kwargs=kwargs)

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        """
        Retry-aware lock management on failure.

        - If task will retry: Keep lock
        - If max retries exceeded: Release lock
        """
        max_retries_exceeded = False
        if hasattr(self, "request") and self.request:
            current_retries = getattr(self.request, "retries", 0)
            max_retries = self.max_retries if self.max_retries is not None else 3
            max_retries_exceeded = current_retries >= max_retries

        if self.release_lock_on_failure or max_retries_exceeded:
            self.release_lock(task_args=args, task_kwargs=kwargs)
            if max_retries_exceeded:
                logger.warning(
                    f"Task {self.name} failed after {current_retries} retries. Lock released.",
                    task_id=task_id,
                    error=str(exc),
                )

        # Log appropriately
        if isinstance(exc, WorkerLostError):
            logger.warning("Task interrupted due to worker loss", task_id=task_id)
        else:
            logger.error(
                f"Task {self.name} failed: {exc}",
                task_id=task_id,
                traceback=einfo.traceback if einfo else None,
            )

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        """Release lock during retry to allow retry task to acquire it."""
        # Release lock so retry can acquire it via apply_async()
        self.release_lock(task_args=args, task_kwargs=kwargs)
        logger.warning(
            f"Task {self.name} retrying (lock released for retry)",
            task_id=task_id,
            retry_count=self.request.retries,
        )
