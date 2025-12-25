"""
CLI-specific workflow discovery utilities.

This module provides CLI-friendly wrappers around the core discovery functions,
converting DiscoveryError to click.ClickException for proper CLI error handling.
"""

import click

# Re-export core discovery functions
from pyworkflow.discovery import (
    DiscoveryError,
    _ensure_project_in_path,  # noqa: F401
    _find_project_root,  # noqa: F401
    _import_module,  # noqa: F401
    _load_yaml_config,  # noqa: F401
)
from pyworkflow.discovery import (
    discover_workflows as _discover_workflows,
)

__all__ = [
    "discover_workflows",
    "DiscoveryError",
    "_find_project_root",
    "_ensure_project_in_path",
    "_import_module",
    "_load_yaml_config",
]


def discover_workflows(
    module_path: str | None = None,
    config: dict | None = None,
    config_path: str | None = None,
) -> None:
    """
    CLI-friendly wrapper for discover_workflows.

    Converts DiscoveryError to click.ClickException for proper CLI error handling.

    Args:
        module_path: Explicit module path to import
        config: Configuration dict containing 'module' or 'modules' key
        config_path: Path to the config file for sys.path resolution

    Raises:
        click.ClickException: If workflow discovery fails
    """
    try:
        _discover_workflows(module_path=module_path, config=config, config_path=config_path)
    except DiscoveryError as e:
        raise click.ClickException(str(e))
