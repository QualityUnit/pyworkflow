"""
PyWorkflow configuration system.

Provides global configuration for runtime, storage, and default settings.

Configuration is loaded in this priority order:
1. Values set via pyworkflow.configure() (highest priority)
2. Environment variables (PYWORKFLOW_*)
3. Values from pyworkflow.config.yaml in current directory
4. Default values

Usage:
    >>> import pyworkflow
    >>> pyworkflow.configure(
    ...     default_runtime="local",
    ...     default_durable=False,
    ...     storage=InMemoryStorageBackend(),
    ... )

Environment Variables:
    PYWORKFLOW_STORAGE_TYPE: Storage backend type (file, memory, sqlite, postgres, mysql)
    PYWORKFLOW_STORAGE_PATH: Path for file/sqlite backends
    PYWORKFLOW_POSTGRES_HOST: PostgreSQL host
    PYWORKFLOW_POSTGRES_PORT: PostgreSQL port
    PYWORKFLOW_POSTGRES_USER: PostgreSQL user
    PYWORKFLOW_POSTGRES_PASSWORD: PostgreSQL password
    PYWORKFLOW_POSTGRES_DATABASE: PostgreSQL database
    PYWORKFLOW_MYSQL_HOST: MySQL host
    PYWORKFLOW_MYSQL_PORT: MySQL port
    PYWORKFLOW_MYSQL_USER: MySQL user
    PYWORKFLOW_MYSQL_PASSWORD: MySQL password
    PYWORKFLOW_MYSQL_DATABASE: MySQL database
    PYWORKFLOW_CELERY_BROKER: Celery broker URL
    PYWORKFLOW_CELERY_RESULT_BACKEND: Celery result backend URL
    PYWORKFLOW_RUNTIME: Default runtime (local, celery)
"""

import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from pyworkflow.storage.base import StorageBackend


def _load_env_storage_config() -> dict[str, Any] | None:
    """
    Load storage configuration from environment variables.

    Returns:
        Storage configuration dict if PYWORKFLOW_STORAGE_TYPE is set, None otherwise
    """
    storage_type = os.getenv("PYWORKFLOW_STORAGE_TYPE") or os.getenv("PYWORKFLOW_STORAGE_BACKEND")
    if not storage_type:
        return None

    storage_type = storage_type.lower()

    if storage_type == "postgres":
        return {
            "type": "postgres",
            "host": os.getenv("PYWORKFLOW_POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("PYWORKFLOW_POSTGRES_PORT", "5432")),
            "user": os.getenv("PYWORKFLOW_POSTGRES_USER", "pyworkflow"),
            "password": os.getenv("PYWORKFLOW_POSTGRES_PASSWORD", ""),
            "database": os.getenv("PYWORKFLOW_POSTGRES_DATABASE", "pyworkflow"),
        }
    elif storage_type == "mysql":
        return {
            "type": "mysql",
            "host": os.getenv("PYWORKFLOW_MYSQL_HOST", "localhost"),
            "port": int(os.getenv("PYWORKFLOW_MYSQL_PORT", "3306")),
            "user": os.getenv("PYWORKFLOW_MYSQL_USER", "pyworkflow"),
            "password": os.getenv("PYWORKFLOW_MYSQL_PASSWORD", ""),
            "database": os.getenv("PYWORKFLOW_MYSQL_DATABASE", "pyworkflow"),
        }
    elif storage_type == "sqlite":
        return {
            "type": "sqlite",
            "base_path": os.getenv("PYWORKFLOW_STORAGE_PATH", "./pyworkflow_data/pyworkflow.db"),
        }
    elif storage_type == "memory":
        return {"type": "memory"}
    elif storage_type == "file":
        return {
            "type": "file",
            "base_path": os.getenv("PYWORKFLOW_STORAGE_PATH", "./pyworkflow_data"),
        }
    else:
        # Unknown type, return as-is and let config_to_storage handle it
        return {"type": storage_type}


def _load_yaml_config() -> dict[str, Any]:
    """
    Load configuration from pyworkflow.config.yaml in current directory.

    Returns:
        Configuration dictionary, empty dict if file not found
    """
    config_path = Path.cwd() / "pyworkflow.config.yaml"
    if not config_path.exists():
        return {}

    try:
        import yaml

        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
            return config
    except ImportError:
        return {}
    except Exception:
        return {}


def _create_storage_from_config(storage_config: dict[str, Any]) -> Optional["StorageBackend"]:
    """Create a storage backend from config dictionary."""
    if not storage_config:
        return None

    from pyworkflow.storage.config import config_to_storage

    return config_to_storage(storage_config)


@dataclass
class PyWorkflowConfig:
    """
    Global configuration for PyWorkflow.

    Attributes:
        default_runtime: Default runtime to use ("local", "celery", etc.)
        default_durable: Whether workflows are durable by default
        default_retries: Default number of retries for steps
        default_recover_on_worker_loss: Whether to auto-recover on worker failure
        default_max_recovery_attempts: Default max recovery attempts on worker failure
        storage: Storage backend instance for durable workflows
        celery_broker: Celery broker URL (for celery runtime)
        aws_region: AWS region (for lambda runtimes)
        event_soft_limit: Log warning when event count reaches this (default: 10000)
        event_hard_limit: Fail workflow when event count reaches this (default: 50000)
        event_warning_interval: Log warning every N events after soft limit (default: 100)
    """

    # Defaults (can be overridden per-workflow)
    default_runtime: str = "local"
    default_durable: bool = False
    default_retries: int = 3

    # Fault tolerance defaults
    default_recover_on_worker_loss: bool | None = (
        None  # None = True for durable, False for transient
    )
    default_max_recovery_attempts: int = 3

    # Infrastructure (app-level only)
    storage: Optional["StorageBackend"] = None
    celery_broker: str | None = None
    aws_region: str | None = None

    # Event limit settings (WARNING: Do not modify unless you understand the implications)
    # These limits prevent runaway workflows from consuming excessive resources
    event_soft_limit: int = 10_000  # Log warning at this count
    event_hard_limit: int = 50_000  # Fail workflow at this count
    event_warning_interval: int = 100  # Log warning every N events after soft limit


def _config_from_env_and_yaml() -> PyWorkflowConfig:
    """
    Create a PyWorkflowConfig from environment variables and YAML file.

    Priority:
    1. Environment variables (PYWORKFLOW_*)
    2. YAML config file (pyworkflow.config.yaml)
    3. Defaults
    """
    yaml_config = _load_yaml_config()
    env_storage_config = _load_env_storage_config()

    # Runtime: env var > yaml > default
    runtime = os.getenv("PYWORKFLOW_RUNTIME") or yaml_config.get("runtime", "local")
    durable = runtime == "celery"  # Celery runtime defaults to durable

    # Storage: env var > yaml > None
    if env_storage_config:
        storage = _create_storage_from_config(env_storage_config)
    elif yaml_config.get("storage"):
        storage = _create_storage_from_config(yaml_config.get("storage", {}))
    else:
        storage = None

    # Celery broker: env var > yaml > None
    celery_config = yaml_config.get("celery", {})
    celery_broker = os.getenv("PYWORKFLOW_CELERY_BROKER") or celery_config.get("broker")

    return PyWorkflowConfig(
        default_runtime=runtime,
        default_durable=durable,
        storage=storage,
        celery_broker=celery_broker,
    )


# Global singleton
_config: PyWorkflowConfig | None = None
_config_loaded_from_yaml: bool = False


def configure(
    *,
    module: str | None = None,
    discover: bool = True,
    **kwargs: Any,
) -> None:
    """
    Configure PyWorkflow defaults.

    Args:
        module: Python module path to discover workflows from (e.g., "myapp.workflows").
            If provided and discover=True, the module will be imported to register
            workflows decorated with @workflow.
        discover: If True (default) and module is provided, automatically discover
            and register workflows from the specified module.
        default_runtime: Default runtime ("local", "celery", "lambda", "durable-lambda")
        default_durable: Whether workflows are durable by default
        default_retries: Default number of retries for steps
        default_recover_on_worker_loss: Whether to auto-recover on worker failure
            (None = True for durable, False for transient)
        default_max_recovery_attempts: Max recovery attempts on worker failure
        storage: Storage backend instance
        celery_broker: Celery broker URL
        aws_region: AWS region

    Event Limit Settings (Advanced - modify with caution):
        event_soft_limit: Log warning when event count reaches this (default: 10000)
        event_hard_limit: Fail workflow when event count reaches this (default: 50000)
        event_warning_interval: Log warning every N events after soft limit (default: 100)

    WARNING: Modifying event limits is not recommended. These defaults are carefully
    chosen to prevent runaway workflows from consuming excessive resources.

    Example:
        >>> import pyworkflow
        >>> from pyworkflow.storage import InMemoryStorageBackend
        >>>
        >>> pyworkflow.configure(
        ...     default_runtime="local",
        ...     default_durable=True,
        ...     storage=InMemoryStorageBackend(),
        ... )

        >>> # Configure with workflow discovery
        >>> pyworkflow.configure(module="myapp.workflows")
    """
    global _config, _config_loaded_from_yaml
    if _config is None:
        # Load from env vars and YAML first, then apply overrides
        _config = _config_from_env_and_yaml()
        _config_loaded_from_yaml = True

    # Warn if user is modifying event limits
    event_limit_keys = {"event_soft_limit", "event_hard_limit", "event_warning_interval"}
    modified_limits = event_limit_keys & set(kwargs.keys())
    if modified_limits:
        warnings.warn(
            f"Modifying event limits ({', '.join(sorted(modified_limits))}) is not recommended. "
            "These defaults are carefully chosen to prevent runaway workflows.",
            UserWarning,
            stacklevel=2,
        )

    for key, value in kwargs.items():
        if hasattr(_config, key):
            setattr(_config, key, value)
        else:
            valid_keys = list(PyWorkflowConfig.__dataclass_fields__.keys())
            raise ValueError(
                f"Unknown config option: {key}. Valid options: {', '.join(valid_keys)}"
            )

    # Auto-discover workflows if module is specified
    if discover and module:
        from pyworkflow.discovery import discover_workflows

        discover_workflows(module_path=module)


def configure_from_yaml(path: str | Path, discover: bool = True) -> None:
    """
    Configure PyWorkflow from a specific YAML file.

    Unlike the automatic YAML loading in get_config(), this function:
    - Requires an explicit path
    - Raises FileNotFoundError if the file doesn't exist
    - Raises ValueError if YAML parsing fails
    - Optionally discovers workflows from the 'module' field in the YAML

    Args:
        path: Path to the YAML configuration file
        discover: If True (default), automatically discover and register
            workflows from the 'module' or 'modules' field in the YAML file.
            Set to False to skip discovery.

    Raises:
        FileNotFoundError: If the specified file doesn't exist
        ValueError: If the YAML file is invalid or cannot be parsed
        ImportError: If PyYAML is not installed
        DiscoveryError: If workflow module discovery fails (when discover=True)

    Example:
        >>> import pyworkflow
        >>> pyworkflow.configure_from_yaml("/etc/pyworkflow/config.yaml")

        >>> # Skip workflow discovery
        >>> pyworkflow.configure_from_yaml("/etc/pyworkflow/config.yaml", discover=False)
    """
    global _config, _config_loaded_from_yaml

    config_path = Path(path)

    if not config_path.exists():
        raise FileNotFoundError(f"PyWorkflow configuration file not found: {config_path}")

    try:
        import yaml
    except ImportError:
        raise ImportError(
            "PyYAML is required for YAML configuration. Install it with: pip install pyyaml"
        )

    try:
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {config_path}: {e}")

    # Map YAML keys to config attributes (same logic as _config_from_yaml)
    runtime = yaml_config.get("runtime", "local")
    durable = runtime == "celery"  # Celery runtime defaults to durable

    # Create storage from config
    storage = _create_storage_from_config(yaml_config.get("storage", {}))

    # Get celery broker
    celery_config = yaml_config.get("celery", {})
    celery_broker = celery_config.get("broker")

    _config = PyWorkflowConfig(
        default_runtime=runtime,
        default_durable=durable,
        storage=storage,
        celery_broker=celery_broker,
    )
    _config_loaded_from_yaml = True

    # Auto-discover workflows if enabled
    if discover:
        from pyworkflow.discovery import discover_workflows

        discover_workflows(config=yaml_config, config_path=config_path)


def get_config() -> PyWorkflowConfig:
    """
    Get the current configuration.

    If not yet configured, loads from environment variables and
    pyworkflow.config.yaml (env vars take priority).

    Returns:
        Current PyWorkflowConfig instance
    """
    global _config, _config_loaded_from_yaml
    if _config is None:
        # Load from env vars and YAML config file
        _config = _config_from_env_and_yaml()
        _config_loaded_from_yaml = True
    return _config


def reset_config() -> None:
    """
    Reset configuration to defaults.

    Primarily used for testing.
    """
    global _config, _config_loaded_from_yaml
    _config = None
    _config_loaded_from_yaml = False


def get_storage() -> Optional["StorageBackend"]:
    """
    Get the configured storage backend.

    Returns:
        StorageBackend instance if configured, None otherwise

    Example:
        >>> import pyworkflow
        >>> from pyworkflow.storage import InMemoryStorageBackend
        >>> pyworkflow.configure(storage=InMemoryStorageBackend())
        >>> storage = pyworkflow.get_storage()
    """
    return get_config().storage
