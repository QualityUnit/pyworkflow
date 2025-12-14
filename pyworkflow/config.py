"""
PyWorkflow configuration system.

Provides global configuration for runtime, storage, and default settings.

Usage:
    >>> import pyworkflow
    >>> pyworkflow.configure(
    ...     default_runtime="local",
    ...     default_durable=False,
    ...     storage=InMemoryStorageBackend(),
    ... )
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from pyworkflow.storage.base import StorageBackend


@dataclass
class PyWorkflowConfig:
    """
    Global configuration for PyWorkflow.

    Attributes:
        default_runtime: Default runtime to use ("local", "celery", etc.)
        default_durable: Whether workflows are durable by default
        default_retries: Default number of retries for steps
        storage: Storage backend instance for durable workflows
        celery_broker: Celery broker URL (for celery runtime)
        aws_region: AWS region (for lambda runtimes)
    """

    # Defaults (can be overridden per-workflow)
    default_runtime: str = "local"
    default_durable: bool = False
    default_retries: int = 3

    # Infrastructure (app-level only)
    storage: Optional["StorageBackend"] = None
    celery_broker: Optional[str] = None
    aws_region: Optional[str] = None


# Global singleton
_config: Optional[PyWorkflowConfig] = None


def configure(**kwargs: Any) -> None:
    """
    Configure PyWorkflow defaults.

    Args:
        default_runtime: Default runtime ("local", "celery", "lambda", "durable-lambda")
        default_durable: Whether workflows are durable by default
        default_retries: Default number of retries for steps
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

    Creates a default configuration if not yet configured.

    Returns:
        Current PyWorkflowConfig instance
    """
    global _config
    if _config is None:
        _config = PyWorkflowConfig()
    return _config


def reset_config() -> None:
    """
    Reset configuration to defaults.

    Primarily used for testing.
    """
    global _config
    _config = None
