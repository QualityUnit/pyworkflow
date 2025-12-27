"""Storage backend factory utilities."""

from typing import Any

from loguru import logger

from pyworkflow import StorageBackend
from pyworkflow.storage.config import config_to_storage


def create_storage(
    backend_type: str | None = None,
    path: str | None = None,
    config: dict[str, Any] | None = None,
) -> StorageBackend:
    """
    Create storage backend from configuration.

    Configuration priority:
    1. CLI flags (backend_type, path arguments)
    2. Environment variables (handled by Click)
    3. Config file (config dict)
    4. Default (file backend with ./workflow_data)

    Args:
        backend_type: Storage backend type ("file", "memory", "redis", "sqlite", "dynamodb")
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
        config = {"storage": {"type": "file", "base_path": "./workflow_data"}}
        storage = create_storage(config=config)

        # Default (file storage)
        storage = create_storage()
    """
    # Resolve backend type with priority: CLI flag > config file > default
    backend = backend_type

    if not backend and config:
        backend = config.get("storage", {}).get("type")

    if not backend:
        backend = "file"  # Default

    logger.debug(f"Creating storage backend: {backend}")

    # Resolve storage path with priority: CLI flag > config file > default
    storage_path = path
    if not storage_path and config:
        storage_path = config.get("storage", {}).get("base_path")

    # Build unified config dict
    storage_config: dict[str, Any] = {"type": backend}
    if storage_path:
        storage_config["base_path"] = storage_path

    # Extract redis config if present
    if backend == "redis" and config:
        storage_section = config.get("storage", {})
        if "host" in storage_section:
            storage_config["host"] = storage_section["host"]
        if "port" in storage_section:
            storage_config["port"] = storage_section["port"]
        if "db" in storage_section:
            storage_config["db"] = storage_section["db"]

    # Extract postgres config if present
    if backend == "postgres" and config:
        storage_section = config.get("storage", {})
        if "dsn" in storage_section:
            storage_config["dsn"] = storage_section["dsn"]
        else:
            if "host" in storage_section:
                storage_config["host"] = storage_section["host"]
            if "port" in storage_section:
                storage_config["port"] = storage_section["port"]
            if "user" in storage_section:
                storage_config["user"] = storage_section["user"]
            if "password" in storage_section:
                storage_config["password"] = storage_section["password"]
            if "database" in storage_section:
                storage_config["database"] = storage_section["database"]

    # Extract dynamodb config if present
    if backend == "dynamodb" and config:
        storage_section = config.get("storage", {})
        if "table_name" in storage_section:
            storage_config["table_name"] = storage_section["table_name"]
        if "region" in storage_section:
            storage_config["region"] = storage_section["region"]
        if "endpoint_url" in storage_section:
            storage_config["endpoint_url"] = storage_section["endpoint_url"]

    # Use unified config_to_storage
    storage = config_to_storage(storage_config)

    # Log which backend was created
    backend_name = storage.__class__.__name__
    if hasattr(storage, "base_path"):
        logger.info(f"Using {backend_name} with path: {storage.base_path}")
    else:
        logger.info(f"Using {backend_name}")

    return storage
