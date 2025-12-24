"""
Unified storage backend configuration utilities.

This module provides functions to serialize storage backends to configuration
dicts and recreate storage backends from configuration dicts. This is used
for passing storage configuration to Celery tasks and other cross-process
communication.
"""

from typing import Any

from pyworkflow.storage.base import StorageBackend


def storage_to_config(storage: StorageBackend | None) -> dict[str, Any] | None:
    """
    Serialize storage backend to configuration dict.

    Args:
        storage: Storage backend instance

    Returns:
        Configuration dict or None if storage is None

    Example:
        >>> from pyworkflow.storage.file import FileStorageBackend
        >>> storage = FileStorageBackend(base_path="./data")
        >>> config = storage_to_config(storage)
        >>> config
        {'type': 'file', 'base_path': './data'}
    """
    if storage is None:
        return None

    # Use class name to avoid import cycles
    class_name = storage.__class__.__name__

    if class_name == "FileStorageBackend":
        return {
            "type": "file",
            "base_path": str(getattr(storage, "base_path", "./workflow_data")),
        }
    elif class_name == "InMemoryStorageBackend":
        return {"type": "memory"}
    elif class_name == "RedisStorageBackend":
        return {
            "type": "redis",
            "host": getattr(storage, "host", "localhost"),
            "port": getattr(storage, "port", 6379),
            "db": getattr(storage, "db", 0),
        }
    else:
        # Unknown backend - return minimal config
        return {"type": "unknown"}


def config_to_storage(config: dict[str, Any] | None = None) -> StorageBackend:
    """
    Create storage backend from configuration dict.

    Args:
        config: Configuration dict with 'type' and backend-specific params.
                If None, returns default FileStorageBackend.

    Returns:
        Storage backend instance

    Raises:
        ValueError: If storage type is unknown

    Example:
        >>> config = {"type": "file", "base_path": "./data"}
        >>> storage = config_to_storage(config)
        >>> isinstance(storage, FileStorageBackend)
        True
    """
    if not config:
        from pyworkflow.storage.file import FileStorageBackend

        return FileStorageBackend()

    storage_type = config.get("type", "file")

    if storage_type == "file":
        from pyworkflow.storage.file import FileStorageBackend

        base_path = config.get("base_path") or "./workflow_data"
        return FileStorageBackend(base_path=base_path)

    elif storage_type == "memory":
        from pyworkflow.storage.memory import InMemoryStorageBackend

        return InMemoryStorageBackend()

    elif storage_type == "redis":
        from pyworkflow.storage.redis import RedisStorageBackend

        return RedisStorageBackend(
            host=config.get("host", "localhost"),
            port=config.get("port", 6379),
            db=config.get("db", 0),
        )

    else:
        raise ValueError(f"Unknown storage type: {storage_type}")
