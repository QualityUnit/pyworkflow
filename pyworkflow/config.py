"""
PyWorkflow configuration system.

Provides global configuration for runtime, storage, and default settings.

Configuration is loaded in this priority order:
1. Values set via pyworkflow.configure() (highest priority)
2. Values from pyworkflow.config.yaml in current directory
3. Default values

Usage:
    >>> import pyworkflow
    >>> pyworkflow.configure(
    ...     default_runtime="local",
    ...     default_durable=False,
    ...     storage=InMemoryStorageBackend(),
    ... )
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from pyworkflow.storage.base import StorageBackend


def _load_yaml_config() -> Dict[str, Any]:
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


def _create_storage_from_config(storage_config: Dict[str, Any]) -> Optional["StorageBackend"]:
    """Create a storage backend from config dictionary."""
    if not storage_config:
        return None

    backend = storage_config.get("backend", "file")
    path = storage_config.get("path", "./workflow_data")

    if backend == "file":
        from pyworkflow.storage.file import FileStorageBackend

        return FileStorageBackend(base_path=path)
    elif backend == "memory":
        from pyworkflow.storage.memory import InMemoryStorageBackend

        return InMemoryStorageBackend()

    return None


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
    """

    # Defaults (can be overridden per-workflow)
    default_runtime: str = "local"
    default_durable: bool = False
    default_retries: int = 3

    # Fault tolerance defaults
    default_recover_on_worker_loss: Optional[bool] = None  # None = True for durable, False for transient
    default_max_recovery_attempts: int = 3

    # Infrastructure (app-level only)
    storage: Optional["StorageBackend"] = None
    celery_broker: Optional[str] = None
    aws_region: Optional[str] = None


def _config_from_yaml() -> PyWorkflowConfig:
    """Create a PyWorkflowConfig from YAML file settings."""
    yaml_config = _load_yaml_config()

    if not yaml_config:
        return PyWorkflowConfig()

    # Map YAML keys to config attributes
    runtime = yaml_config.get("runtime", "local")
    durable = runtime == "celery"  # Celery runtime defaults to durable

    # Create storage from config
    storage = _create_storage_from_config(yaml_config.get("storage", {}))

    # Get celery broker
    celery_config = yaml_config.get("celery", {})
    celery_broker = celery_config.get("broker")

    return PyWorkflowConfig(
        default_runtime=runtime,
        default_durable=durable,
        storage=storage,
        celery_broker=celery_broker,
    )


# Global singleton
_config: Optional[PyWorkflowConfig] = None
_config_loaded_from_yaml: bool = False


def configure(**kwargs: Any) -> None:
    """
    Configure PyWorkflow defaults.

    Args:
        default_runtime: Default runtime ("local", "celery", "lambda", "durable-lambda")
        default_durable: Whether workflows are durable by default
        default_retries: Default number of retries for steps
        default_recover_on_worker_loss: Whether to auto-recover on worker failure
            (None = True for durable, False for transient)
        default_max_recovery_attempts: Max recovery attempts on worker failure
        storage: Storage backend instance
        celery_broker: Celery broker URL
        aws_region: AWS region

    Example:
        >>> import pyworkflow
        >>> from pyworkflow.storage import InMemoryStorageBackend
        >>>
        >>> pyworkflow.configure(
        ...     default_runtime="local",
        ...     default_durable=True,
        ...     storage=InMemoryStorageBackend(),
        ... )
    """
    global _config
    if _config is None:
        _config = PyWorkflowConfig()

    for key, value in kwargs.items():
        if hasattr(_config, key):
            setattr(_config, key, value)
        else:
            valid_keys = [f for f in PyWorkflowConfig.__dataclass_fields__.keys()]
            raise ValueError(
                f"Unknown config option: {key}. Valid options: {', '.join(valid_keys)}"
            )


def get_config() -> PyWorkflowConfig:
    """
    Get the current configuration.

    If not yet configured, loads from pyworkflow.config.yaml if present,
    otherwise creates default configuration.

    Returns:
        Current PyWorkflowConfig instance
    """
    global _config, _config_loaded_from_yaml
    if _config is None:
        # Try to load from YAML config file first
        _config = _config_from_yaml()
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
