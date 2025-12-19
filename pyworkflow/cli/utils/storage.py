"""Storage backend factory utilities."""

from typing import Dict, Any, Optional

from pyworkflow import FileStorageBackend, InMemoryStorageBackend, StorageBackend
from loguru import logger


def create_storage(
    backend_type: Optional[str] = None,
    path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> StorageBackend:
    """
    Create storage backend from configuration.

    Configuration priority:
    1. CLI flags (backend_type, path arguments)
    2. Environment variables (handled by Click)
    3. Config file (config dict)
    4. Default (file backend with ./workflow_data)

    Args:
        backend_type: Storage backend type ("file", "memory", "redis", "sqlite")
        path: Storage path (for file/sqlite backends)
        config: Configuration dict from pyworkflow.toml

    Returns:
        Configured StorageBackend instance

    Raises:
        ValueError: If backend type is unsupported

    Examples:
        # File storage with explicit path
        storage = create_storage(backend_type="file", path="./data")

        # From config
        config = {"storage": {"backend": "file", "path": "./workflow_data"}}
        storage = create_storage(config=config)

        # Default (file storage)
        storage = create_storage()
    """
    # Resolve backend type
    backend = backend_type

    if not backend and config:
        backend = config.get("storage", {}).get("backend")

    if not backend:
        backend = "file"  # Default

    logger.debug(f"Creating storage backend: {backend}")

    # Create backend based on type
    if backend == "memory":
        logger.info("Using InMemoryStorageBackend")
        return InMemoryStorageBackend()

    elif backend == "file":
        # Resolve storage path
        storage_path = path

        if not storage_path and config:
            storage_path = config.get("storage", {}).get("path")

        if not storage_path:
            storage_path = "./workflow_data"  # Default

        logger.info(f"Using FileStorageBackend with path: {storage_path}")
        return FileStorageBackend(base_path=storage_path)

    elif backend == "redis":
        # Redis support (future enhancement)
        redis_url = config.get("storage", {}).get("redis_url") if config else None
        if not redis_url:
            redis_url = "redis://localhost:6379/0"

        logger.warning("Redis backend not yet implemented in CLI")
        raise ValueError(
            "Redis backend is not yet supported in the CLI. "
            "Use 'file' or 'memory' backends."
        )

    elif backend == "sqlite":
        # SQLite support (future enhancement)
        db_path = path or (config.get("storage", {}).get("db_path") if config else None)
        if not db_path:
            db_path = "./workflows.db"

        logger.warning("SQLite backend not yet implemented in CLI")
        raise ValueError(
            "SQLite backend is not yet supported in the CLI. "
            "Use 'file' or 'memory' backends."
        )

    else:
        raise ValueError(
            f"Unsupported storage backend: {backend}. "
            f"Supported backends: file, memory"
        )
