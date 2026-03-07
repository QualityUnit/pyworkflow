"""
CheckpointBackend ABC and built-in implementations.

Checkpoints allow stream steps to persist custom state across
suspend/resume cycles.
"""

from abc import ABC, abstractmethod
from typing import Any

from loguru import logger


class CheckpointBackend(ABC):
    """Abstract base class for checkpoint storage backends."""

    @abstractmethod
    async def save(self, step_run_id: str, data: dict) -> None:
        """Save checkpoint data for a stream step."""
        ...

    @abstractmethod
    async def load(self, step_run_id: str) -> dict | None:
        """Load checkpoint data for a stream step."""
        ...

    @abstractmethod
    async def delete(self, step_run_id: str) -> None:
        """Delete checkpoint data for a stream step."""
        ...


class DefaultCheckpointBackend(CheckpointBackend):
    """
    Checkpoint backend that uses PyWorkflow's configured StorageBackend.

    This is the default — checkpoint data is stored alongside workflow data.
    """

    def __init__(self, storage: Any = None) -> None:
        self._storage = storage

    def _get_storage(self) -> Any:
        if self._storage is not None:
            return self._storage
        from pyworkflow.config import get_config

        config = get_config()
        if config.storage is None:
            raise RuntimeError(
                "No storage backend configured. " "Call pyworkflow.configure(storage=...) first."
            )
        return config.storage

    async def save(self, step_run_id: str, data: dict) -> None:
        """Save checkpoint using PyWorkflow storage."""
        storage = self._get_storage()
        await storage.save_checkpoint(step_run_id, data)
        logger.debug(f"Checkpoint saved for {step_run_id}")

    async def load(self, step_run_id: str) -> dict | None:
        """Load checkpoint from PyWorkflow storage."""
        storage = self._get_storage()
        data = await storage.load_checkpoint(step_run_id)
        if data is not None:
            logger.debug(f"Checkpoint loaded for {step_run_id}")
        return data

    async def delete(self, step_run_id: str) -> None:
        """Delete checkpoint from PyWorkflow storage."""
        storage = self._get_storage()
        await storage.delete_checkpoint(step_run_id)
        logger.debug(f"Checkpoint deleted for {step_run_id}")


class RedisCheckpointBackend(CheckpointBackend):
    """
    Checkpoint backend using Redis.

    Configured via pyworkflow.configure() or environment variables:
    - PYWORKFLOW_CHECKPOINT_BACKEND_URL: Redis connection URL
    """

    def __init__(self, url: str = "redis://localhost:6379/1") -> None:
        self._url = url
        self._redis: Any = None

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(self._url)
            except ImportError:
                raise RuntimeError(
                    "redis package required for RedisCheckpointBackend. "
                    "Install with: pip install redis"
                )
        return self._redis

    async def save(self, step_run_id: str, data: dict) -> None:
        """Save checkpoint to Redis."""
        import json

        r = await self._get_redis()
        key = f"pyworkflow:checkpoint:{step_run_id}"
        await r.set(key, json.dumps(data))
        logger.debug(f"Checkpoint saved to Redis for {step_run_id}")

    async def load(self, step_run_id: str) -> dict | None:
        """Load checkpoint from Redis."""
        import json

        r = await self._get_redis()
        key = f"pyworkflow:checkpoint:{step_run_id}"
        raw = await r.get(key)
        if raw is None:
            return None
        logger.debug(f"Checkpoint loaded from Redis for {step_run_id}")
        return json.loads(raw)

    async def delete(self, step_run_id: str) -> None:
        """Delete checkpoint from Redis."""
        r = await self._get_redis()
        key = f"pyworkflow:checkpoint:{step_run_id}"
        await r.delete(key)
        logger.debug(f"Checkpoint deleted from Redis for {step_run_id}")


# Backend registry
_checkpoint_backends: dict[str, type[CheckpointBackend]] = {
    "default": DefaultCheckpointBackend,
    "redis": RedisCheckpointBackend,
}

# Active backend instance (lazy-initialized)
_active_backend: CheckpointBackend | None = None
_configured_backend_name: str = "default"
_configured_backend_url: str | None = None


def register_checkpoint_backend(name: str, backend_class: type[CheckpointBackend]) -> None:
    """Register a custom checkpoint backend."""
    _checkpoint_backends[name] = backend_class


def configure_checkpoint_backend(
    backend: str = "default",
    url: str | None = None,
) -> None:
    """
    Configure the checkpoint backend.

    Args:
        backend: Backend name ("default", "redis", or custom registered name)
        url: Connection URL (for backends that need it)
    """
    global _active_backend, _configured_backend_name, _configured_backend_url
    _configured_backend_name = backend
    _configured_backend_url = url
    _active_backend = None  # Reset to force re-initialization


def get_checkpoint_backend(storage: Any = None) -> CheckpointBackend:
    """Get the configured checkpoint backend, creating it if needed."""
    global _active_backend

    if _active_backend is not None:
        return _active_backend

    # Check environment variables
    import os

    backend_name = os.environ.get("PYWORKFLOW_CHECKPOINT_BACKEND", _configured_backend_name)
    backend_url = os.environ.get("PYWORKFLOW_CHECKPOINT_BACKEND_URL", _configured_backend_url)

    backend_class = _checkpoint_backends.get(backend_name)
    if backend_class is None:
        raise ValueError(
            f"Unknown checkpoint backend: {backend_name}. "
            f"Available: {list(_checkpoint_backends.keys())}"
        )

    if backend_name == "default":
        _active_backend = DefaultCheckpointBackend(storage=storage)
    elif backend_name == "redis":
        _active_backend = RedisCheckpointBackend(url=backend_url or "redis://localhost:6379/1")
    elif backend_url:
        _active_backend = backend_class(url=backend_url)  # type: ignore[call-arg]
    else:
        _active_backend = backend_class()

    return _active_backend


def reset_checkpoint_backend() -> None:
    """Reset the checkpoint backend (for testing)."""
    global _active_backend, _configured_backend_name, _configured_backend_url
    _active_backend = None
    _configured_backend_name = "default"
    _configured_backend_url = None
