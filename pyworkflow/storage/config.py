"""
Unified storage backend configuration utilities.

This module provides functions to serialize storage backends to configuration
dicts and recreate storage backends from configuration dicts. This is used
for passing storage configuration to Celery tasks and other cross-process
communication.

Storage backends are cached per-process to reuse connection pools and avoid
connection exhaustion (e.g., "too many clients" errors with PostgreSQL).

Note: For async backends (postgres, mysql), the backends handle event loop
changes internally by detecting loop mismatches and recreating the pool.
"""

import contextlib
import hashlib
import json
from typing import Any

from pyworkflow.storage.base import StorageBackend

# Module-level cache for storage backends (per-worker singleton pattern)
# Key: hash of config dict, Value: tuple of (StorageBackend, reserved for future use)
_storage_cache: dict[str, tuple[StorageBackend, None]] = {}


def _config_to_cache_key(config: dict[str, Any] | None) -> str:
    """
    Create a cache key from config dict.

    Args:
        config: Configuration dict

    Returns:
        Cache key string (MD5 hash of serialized config)
    """
    if config is None:
        return "default"
    # Sort keys for consistent hashing
    serialized = json.dumps(config, sort_keys=True)
    return hashlib.md5(serialized.encode()).hexdigest()


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
    elif class_name == "SQLiteStorageBackend":
        return {
            "type": "sqlite",
            "base_path": str(getattr(storage, "db_path", "./pyworkflow_data/pyworkflow.db")),
        }
    elif class_name == "RedisStorageBackend":
        return {
            "type": "redis",
            "host": getattr(storage, "host", "localhost"),
            "port": getattr(storage, "port", 6379),
            "db": getattr(storage, "db", 0),
        }
    elif class_name == "PostgresStorageBackend":
        config: dict[str, Any] = {"type": "postgres"}
        dsn = getattr(storage, "dsn", None)
        if dsn:
            config["dsn"] = dsn
        else:
            config["host"] = getattr(storage, "host", "localhost")
            config["port"] = getattr(storage, "port", 5432)
            config["user"] = getattr(storage, "user", "pyworkflow")
            config["password"] = getattr(storage, "password", "")
            config["database"] = getattr(storage, "database", "pyworkflow")
        return config
    elif class_name == "DynamoDBStorageBackend":
        return {
            "type": "dynamodb",
            "table_name": getattr(storage, "table_name", "pyworkflow"),
            "region": getattr(storage, "region", "us-east-1"),
            "endpoint_url": getattr(storage, "endpoint_url", None),
        }
    elif class_name == "CassandraStorageBackend":
        return {
            "type": "cassandra",
            "contact_points": getattr(storage, "contact_points", ["localhost"]),
            "port": getattr(storage, "port", 9042),
            "keyspace": getattr(storage, "keyspace", "pyworkflow"),
            "username": getattr(storage, "username", None),
            "password": getattr(storage, "password", None),
            "read_consistency": getattr(storage, "read_consistency", "LOCAL_QUORUM"),
            "write_consistency": getattr(storage, "write_consistency", "LOCAL_QUORUM"),
            "replication_strategy": getattr(storage, "replication_strategy", "SimpleStrategy"),
            "replication_factor": getattr(storage, "replication_factor", 3),
            "datacenter": getattr(storage, "datacenter", None),
        }
    elif class_name == "MySQLStorageBackend":
        config = {"type": "mysql"}
        dsn = getattr(storage, "dsn", None)
        if dsn:
            config["dsn"] = dsn
        else:
            config["host"] = getattr(storage, "host", "localhost")
            config["port"] = getattr(storage, "port", 3306)
            config["user"] = getattr(storage, "user", "pyworkflow")
            config["password"] = getattr(storage, "password", "")
            config["database"] = getattr(storage, "database", "pyworkflow")
        return config
    else:
        # Unknown backend - return minimal config
        return {"type": "unknown"}


def config_to_storage(config: dict[str, Any] | None = None) -> StorageBackend:
    """
    Create or return cached storage backend from configuration dict.

    Storage backends are cached per-process to reuse connection pools.
    This prevents connection exhaustion with pooled backends like PostgreSQL.

    For async backends (postgres, mysql), the backend handles event loop
    changes internally by detecting loop mismatches and recreating the pool.

    Args:
        config: Configuration dict with 'type' and backend-specific params.
                If None, returns default FileStorageBackend.

    Returns:
        Storage backend instance (may be cached)

    Raises:
        ValueError: If storage type is unknown

    Example:
        >>> config = {"type": "file", "base_path": "./data"}
        >>> storage = config_to_storage(config)
        >>> isinstance(storage, FileStorageBackend)
        True
    """
    cache_key = _config_to_cache_key(config)

    if cache_key in _storage_cache:
        cached_storage, _ = _storage_cache[cache_key]
        return cached_storage

    # Create new instance
    storage = _create_storage_backend(config)
    _storage_cache[cache_key] = (storage, None)
    return storage


def _create_storage_backend(config: dict[str, Any] | None) -> StorageBackend:
    """
    Internal function that creates a new storage backend instance.

    This should not be called directly - use config_to_storage() instead
    to benefit from caching.
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

    elif storage_type == "sqlite":
        try:
            from pyworkflow.storage.sqlite import SQLiteStorageBackend
        except ImportError:
            raise ValueError(
                "SQLite storage backend is not available. "
                "Python was compiled without SQLite support (_sqlite3 module missing). "
                "Please use 'file' or 'memory' storage instead, or rebuild Python with SQLite support."
            )

        db_path = config.get("base_path") or "./pyworkflow_data/pyworkflow.db"
        return SQLiteStorageBackend(db_path=db_path)

    elif storage_type == "redis":
        try:
            from pyworkflow.storage.redis import RedisStorageBackend
        except ImportError:
            raise ValueError(
                "Redis storage backend is not yet implemented. "
                "Use 'file', 'sqlite', or 'postgres' storage. "
                "Redis support is planned for a future release. "
                "Note: Redis can still be used as a Celery broker with 'pip install pyworkflow[redis]'."
            )

        return RedisStorageBackend(
            host=config.get("host", "localhost"),
            port=config.get("port", 6379),
            db=config.get("db", 0),
        )

    elif storage_type == "postgres":
        try:
            from pyworkflow.storage.postgres import PostgresStorageBackend
        except ImportError:
            raise ValueError(
                "PostgreSQL storage backend is not available. Install asyncpg: pip install asyncpg"
            )

        # Support both DSN and individual parameters
        if "dsn" in config:
            return PostgresStorageBackend(dsn=config["dsn"])
        else:
            return PostgresStorageBackend(
                host=config.get("host", "localhost"),
                port=config.get("port", 5432),
                user=config.get("user", "pyworkflow"),
                password=config.get("password", ""),
                database=config.get("database", "pyworkflow"),
            )

    elif storage_type == "dynamodb":
        try:
            from pyworkflow.storage.dynamodb import DynamoDBStorageBackend
        except ImportError:
            raise ValueError(
                "DynamoDB storage backend is not available. "
                "Please install the required dependencies with: pip install 'pyworkflow[dynamodb]'"
            )

        return DynamoDBStorageBackend(
            table_name=config.get("table_name", "pyworkflow"),
            region=config.get("region", "us-east-1"),
            endpoint_url=config.get("endpoint_url"),
        )

    elif storage_type == "cassandra":
        try:
            from pyworkflow.storage.cassandra import CassandraStorageBackend
        except ImportError:
            raise ValueError(
                "Cassandra storage backend is not available. "
                "Please install the required dependencies with: pip install 'pyworkflow[cassandra]'"
            )

        return CassandraStorageBackend(
            contact_points=config.get("contact_points", ["localhost"]),
            port=config.get("port", 9042),
            keyspace=config.get("keyspace", "pyworkflow"),
            username=config.get("username"),
            password=config.get("password"),
            read_consistency=config.get("read_consistency", "LOCAL_QUORUM"),
            write_consistency=config.get("write_consistency", "LOCAL_QUORUM"),
            replication_strategy=config.get("replication_strategy", "SimpleStrategy"),
            replication_factor=config.get("replication_factor", 3),
            datacenter=config.get("datacenter"),
        )

    elif storage_type == "mysql":
        try:
            from pyworkflow.storage.mysql import MySQLStorageBackend
        except ImportError:
            raise ValueError(
                "MySQL storage backend is not available. "
                "Please install the required dependencies with: pip install 'pyworkflow[mysql]'"
            )

        # Support both DSN and individual parameters
        if "dsn" in config:
            return MySQLStorageBackend(dsn=config["dsn"])
        else:
            return MySQLStorageBackend(
                host=config.get("host", "localhost"),
                port=config.get("port", 3306),
                user=config.get("user", "pyworkflow"),
                password=config.get("password", ""),
                database=config.get("database", "pyworkflow"),
            )

    else:
        raise ValueError(f"Unknown storage type: {storage_type}")


async def disconnect_all_cached() -> None:
    """
    Disconnect all cached storage backends.

    Call this on worker shutdown to properly close connection pools.
    This is automatically called by the Celery worker_shutdown signal handler.
    """
    for storage, _ in _storage_cache.values():
        if hasattr(storage, "disconnect"):
            with contextlib.suppress(Exception):
                await storage.disconnect()
    _storage_cache.clear()


def clear_storage_cache() -> None:
    """
    Clear the storage cache without disconnecting.

    Primarily used for testing to ensure fresh instances.
    For production cleanup, use disconnect_all_cached() instead.
    """
    _storage_cache.clear()
