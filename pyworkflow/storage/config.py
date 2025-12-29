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
