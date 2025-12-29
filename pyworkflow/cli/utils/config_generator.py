"""
Configuration file generation utilities.

This module provides functions for generating and managing pyworkflow.config.yaml
configuration files.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def generate_yaml_config(
    module: str | None,
    runtime: str,
    storage_type: str,
    storage_path: str | None,
    broker_url: str,
    result_backend: str,
    postgres_host: str | None = None,
    postgres_port: str | None = None,
    postgres_user: str | None = None,
    postgres_password: str | None = None,
    postgres_database: str | None = None,
    mysql_host: str | None = None,
    mysql_port: str | None = None,
    mysql_user: str | None = None,
    mysql_password: str | None = None,
    mysql_database: str | None = None,
    dynamodb_table_name: str | None = None,
    dynamodb_region: str | None = None,
    dynamodb_endpoint_url: str | None = None,
    cassandra_contact_points: list[str] | None = None,
    cassandra_port: str | None = None,
    cassandra_keyspace: str | None = None,
    cassandra_user: str | None = None,
    cassandra_password: str | None = None,
) -> str:
    """
    Generate YAML configuration content.

    Args:
        module: Optional workflow module path (e.g., "myapp.workflows")
        runtime: Runtime type (e.g., "celery", "local")
        storage_type: Storage backend type (e.g., "sqlite", "file", "memory", "postgres",
            "cassandra")
        storage_path: Optional storage path for file/sqlite backends
        broker_url: Celery broker URL
        result_backend: Celery result backend URL
        postgres_host: PostgreSQL host (for postgres backend)
        postgres_port: PostgreSQL port (for postgres backend)
        postgres_user: PostgreSQL user (for postgres backend)
        postgres_password: PostgreSQL password (for postgres backend)
        postgres_database: PostgreSQL database name (for postgres backend)
        dynamodb_table_name: Optional DynamoDB table name
        dynamodb_region: Optional AWS region for DynamoDB
        dynamodb_endpoint_url: Optional local DynamoDB endpoint URL
        cassandra_contact_points: List of Cassandra contact points (for cassandra backend)
        cassandra_port: Cassandra CQL native transport port (for cassandra backend)
        cassandra_keyspace: Cassandra keyspace name (for cassandra backend)
        cassandra_user: Optional Cassandra user (for cassandra backend)
        cassandra_password: Optional Cassandra password (for cassandra backend)

    Returns:
        YAML configuration as string

    Example:
        >>> yaml_content = generate_yaml_config(
        ...     module="myapp.workflows",
        ...     runtime="celery",
        ...     storage_type="sqlite",
        ...     storage_path="./pyworkflow_data/pyworkflow.db",
        ...     broker_url="redis://localhost:6379/0",
        ...     result_backend="redis://localhost:6379/1"
        ... )
    """
    config: dict[str, Any] = {}

    # Add module if provided
    if module:
        config["module"] = module

    # Runtime configuration
    config["runtime"] = runtime

    # Storage configuration
    storage_config: dict[str, Any] = {"type": storage_type}
    if storage_path and storage_type in ["file", "sqlite"]:
        storage_config["base_path"] = storage_path
    if storage_type == "postgres":
        if postgres_host:
            storage_config["host"] = postgres_host
        if postgres_port:
            storage_config["port"] = int(postgres_port)
        if postgres_user:
            storage_config["user"] = postgres_user
        if postgres_password:
            storage_config["password"] = postgres_password
        if postgres_database:
            storage_config["database"] = postgres_database
    elif storage_type == "mysql":
        if mysql_host:
            storage_config["host"] = mysql_host
        if mysql_port:
            storage_config["port"] = int(mysql_port)
        if mysql_user:
            storage_config["user"] = mysql_user
        if mysql_password:
            storage_config["password"] = mysql_password
        if mysql_database:
            storage_config["database"] = mysql_database
    elif storage_type == "dynamodb":
        if dynamodb_table_name:
            storage_config["table_name"] = dynamodb_table_name
        if dynamodb_region:
            storage_config["region"] = dynamodb_region
        if dynamodb_endpoint_url:
            storage_config["endpoint_url"] = dynamodb_endpoint_url
    elif storage_type == "cassandra":
        if cassandra_contact_points:
            storage_config["contact_points"] = cassandra_contact_points
        if cassandra_port:
            storage_config["port"] = int(cassandra_port)
        if cassandra_keyspace:
            storage_config["keyspace"] = cassandra_keyspace
        if cassandra_user:
            storage_config["username"] = cassandra_user
        if cassandra_password:
            storage_config["password"] = cassandra_password
    config["storage"] = storage_config

    # Celery configuration (only for celery runtime)
    if runtime == "celery":
        config["celery"] = {
            "broker": broker_url,
            "result_backend": result_backend,
        }

    # Generate YAML with header comment
    header = f"""# PyWorkflow Configuration
# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
# Documentation: https://docs.pyworkflow.dev

"""

    # Convert to YAML with nice formatting
    yaml_content = yaml.dump(
        config,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    return header + yaml_content


def write_yaml_config(
    config_content: str,
    path: Path | None = None,
    backup: bool = True,
) -> Path:
    """
    Write YAML configuration to file.

    Args:
        config_content: YAML content string
        path: Target file path (default: ./pyworkflow.config.yaml)
        backup: If True, backup existing config before overwriting

    Returns:
        Path to written config file

    Example:
        >>> yaml_content = generate_yaml_config(...)
        >>> config_path = write_yaml_config(yaml_content)
        >>> print(f"Config written to {config_path}")
    """
    path = Path.cwd() / "pyworkflow.config.yaml" if path is None else Path(path)

    # Backup existing config if requested
    if backup and path.exists():
        backup_path = path.with_suffix(".yaml.backup")
        backup_path.write_text(path.read_text())

    # Write new config
    path.write_text(config_content)

    return path


def load_yaml_config(path: Path | None = None) -> dict[str, Any]:
    """
    Load YAML configuration from file.

    Args:
        path: Config file path (default: ./pyworkflow.config.yaml)

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If YAML is invalid

    Example:
        >>> config = load_yaml_config()
        >>> print(config.get("runtime"))
        celery
    """
    path = Path.cwd() / "pyworkflow.config.yaml" if path is None else Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        with open(path) as f:
            config = yaml.safe_load(f)

        # Handle empty config file (yaml.safe_load returns None for empty files)
        if config is None:
            raise ValueError(
                "Config file is empty or contains only comments. "
                "Please add valid configuration or delete the file to create a new one."
            )

        # Ensure it's a dict
        if not isinstance(config, dict):
            raise ValueError("Config file must contain a YAML dictionary")

        return config
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in config file: {e}")


def find_yaml_config(start_path: Path | None = None) -> Path | None:
    """
    Find pyworkflow.config.yaml in current directory or parents.

    Args:
        start_path: Starting directory (default: current working directory)

    Returns:
        Path to config file if found, None otherwise

    Example:
        >>> config_path = find_yaml_config()
        >>> if config_path:
        ...     print(f"Found config at {config_path}")
    """
    start_path = Path.cwd() if start_path is None else Path(start_path)

    # Search current directory and parents
    for directory in [start_path] + list(start_path.parents):
        config_path = directory / "pyworkflow.config.yaml"
        if config_path.exists():
            return config_path

    return None


def display_config_summary(config: dict[str, Any]) -> list[str]:
    """
    Generate a human-readable summary of configuration.

    Args:
        config: Configuration dictionary

    Returns:
        List of summary lines

    Example:
        >>> config = {"runtime": "celery", "storage": {"type": "sqlite"}}
        >>> for line in display_config_summary(config):
        ...     print(line)
    """
    lines = []
    lines.append("Configuration Summary:")
    lines.append("=" * 50)

    # Module
    if "module" in config:
        lines.append(f"  Workflow Module: {config['module']}")
    else:
        lines.append("  Workflow Module: (not configured)")

    # Runtime
    runtime = config.get("runtime", "local")
    lines.append(f"  Runtime: {runtime}")

    # Storage
    storage = config.get("storage", {})
    storage_type = storage.get("type", "file")
    lines.append(f"  Storage Type: {storage_type}")

    if "base_path" in storage:
        lines.append(f"  Storage Path: {storage['base_path']}")
    if storage_type == "postgres":
        host = storage.get("host", "localhost")
        port = storage.get("port", 5432)
        database = storage.get("database", "pyworkflow")
        user = storage.get("user", "pyworkflow")
        lines.append(f"  PostgreSQL: {user}@{host}:{port}/{database}")

    # MySQL-specific config
    if storage_type == "mysql":
        host = storage.get("host", "localhost")
        port = storage.get("port", 3306)
        database = storage.get("database", "pyworkflow")
        user = storage.get("user", "pyworkflow")
        lines.append(f"  MySQL: {user}@{host}:{port}/{database}")

    # DynamoDB-specific config
    if storage_type == "dynamodb":
        if "table_name" in storage:
            lines.append(f"  DynamoDB Table: {storage['table_name']}")
        if "region" in storage:
            lines.append(f"  AWS Region: {storage['region']}")
        if "endpoint_url" in storage:
            lines.append(f"  Endpoint URL: {storage['endpoint_url']}")

    # Cassandra-specific config
    if storage_type == "cassandra":
        contact_points = storage.get("contact_points", ["localhost"])
        port = storage.get("port", 9042)
        keyspace = storage.get("keyspace", "pyworkflow")
        hosts = ", ".join(contact_points) if isinstance(contact_points, list) else contact_points
        lines.append(f"  Cassandra: {hosts}:{port}/{keyspace}")
        if "username" in storage:
            lines.append(f"  Cassandra User: {storage['username']}")

    # Celery (if applicable)
    if runtime == "celery" and "celery" in config:
        celery = config["celery"]
        lines.append(f"  Broker: {celery.get('broker', 'N/A')}")
        lines.append(f"  Result Backend: {celery.get('result_backend', 'N/A')}")

    lines.append("=" * 50)

    return lines


def validate_config(config: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate configuration dictionary.

    Args:
        config: Configuration dictionary to validate

    Returns:
        Tuple of (is_valid, list of error messages)

    Example:
        >>> config = {"runtime": "celery"}
        >>> valid, errors = validate_config(config)
        >>> if not valid:
        ...     for error in errors:
        ...         print(f"Error: {error}")
    """
    errors = []

    # Check runtime
    runtime = config.get("runtime")
    if not runtime:
        errors.append("Missing 'runtime' configuration")
    elif runtime not in ["local", "celery"]:
        errors.append(f"Invalid runtime: {runtime}. Must be 'local' or 'celery'")

    # Check storage
    storage = config.get("storage")
    if not storage:
        errors.append("Missing 'storage' configuration")
    elif not isinstance(storage, dict):
        errors.append("'storage' must be a dictionary")
    else:
        storage_type = storage.get("type")
        if not storage_type:
            errors.append("Missing storage 'type'")
        elif storage_type not in [
            "file",
            "memory",
            "sqlite",
            "redis",
            "postgres",
            "mysql",
            "dynamodb",
            "cassandra",
        ]:
            errors.append(
                f"Invalid storage type: {storage_type}. "
                "Must be 'file', 'memory', 'sqlite', 'redis', 'postgres', 'mysql', 'dynamodb' "
                "or 'cassandra'"
            )

    # Check Celery config if using celery runtime
    if runtime == "celery":
        celery = config.get("celery")
        if not celery:
            errors.append("Missing 'celery' configuration for celery runtime")
        elif not isinstance(celery, dict):
            errors.append("'celery' must be a dictionary")
        else:
            if not celery.get("broker"):
                errors.append("Missing celery 'broker' URL")
            if not celery.get("result_backend"):
                errors.append("Missing celery 'result_backend' URL")

    # Module validation (optional but if present should be valid)
    if "module" in config:
        module = config["module"]
        if not isinstance(module, str):
            errors.append("'module' must be a string")
        elif " " in module:
            errors.append("'module' path cannot contain spaces")

    return len(errors) == 0, errors
