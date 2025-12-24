"""Workflow discovery utilities."""

import importlib
import os
import sys
from pathlib import Path
from typing import Any

import click
from loguru import logger


def _find_project_root() -> Path | None:
    """
    Find the project root by looking for common project markers.

    Searches upward from the current directory for:
    - pyproject.toml
    - setup.py
    - .git directory

    Returns:
        Path to project root if found, None otherwise
    """
    current = Path.cwd()

    for path in [current] + list(current.parents):
        if (path / "pyproject.toml").exists():
            return path
        if (path / "setup.py").exists():
            return path
        if (path / ".git").exists():
            return path

    return None


def _ensure_project_in_path() -> None:
    """Add the project root and current directory to sys.path if not already present."""
    # Add current directory first
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
        logger.debug(f"Added current directory to path: {cwd}")

    # Add project root
    project_root = _find_project_root()
    if project_root:
        root_str = str(project_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
            logger.debug(f"Added project root to path: {root_str}")


def _import_module(module_path: str) -> bool:
    """
    Import a single module to trigger workflow registration.

    Args:
        module_path: Python module path (e.g., "myapp.workflows")

    Returns:
        True if import succeeded, False otherwise
    """
    try:
        importlib.import_module(module_path)
        logger.info(f"Imported module: {module_path}")
        return True
    except ModuleNotFoundError as e:
        logger.error(f"Failed to import module '{module_path}': {e}")
        return False
    except Exception as e:
        logger.error(f"Error importing module '{module_path}': {e}")
        return False


def _load_yaml_config() -> dict[str, Any] | None:
    """
    Load pyworkflow.config.yaml from current directory.

    Returns:
        Configuration dictionary if found, None otherwise
    """
    config_path = Path.cwd() / "pyworkflow.config.yaml"
    if not config_path.exists():
        return None

    try:
        import yaml

        with open(config_path) as f:
            config = yaml.safe_load(f)
            logger.info(f"Loaded config from: {config_path}")
            return config
    except ImportError:
        logger.warning("PyYAML not installed, skipping YAML config")
        return None
    except Exception as e:
        logger.error(f"Failed to load YAML config: {e}")
        return None


def discover_workflows(
    module_path: str | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    """
    Import Python modules to trigger workflow registration.

    Workflows are registered when their module is imported, as the @workflow
    decorator registers them in the global registry. This function handles
    importing the appropriate module based on configuration priority.

    Priority:
    1. Explicit module_path argument (from --module flag)
    2. PYWORKFLOW_DISCOVER environment variable
    3. pyworkflow.config.yaml in current directory

    Args:
        module_path: Explicit module path to import
        config: Configuration dict (currently unused, kept for compatibility)

    Examples:
        # Explicit module
        discover_workflows("myapp.workflows")

        # From environment variable
        os.environ["PYWORKFLOW_DISCOVER"] = "myapp.workflows"
        discover_workflows()

        # From pyworkflow.config.yaml
        # Create file with: module: myapp.workflows
        discover_workflows()
    """
    # Ensure project root is in Python path for module imports
    _ensure_project_in_path()

    # Priority 1: Explicit module path (--module flag)
    if module_path:
        logger.debug(f"Discovering from --module: {module_path}")
        if not _import_module(module_path):
            raise click.ClickException(
                f"Cannot import module '{module_path}'. "
                f"Make sure the module exists and is in your Python path."
            )
        return

    # Priority 2: Environment variable
    env_modules = os.getenv("PYWORKFLOW_DISCOVER", "")
    if env_modules:
        logger.debug(f"Discovering from PYWORKFLOW_DISCOVER: {env_modules}")
        modules = [m.strip() for m in env_modules.split(",") if m.strip()]
        failed = []
        for module in modules:
            if not _import_module(module):
                failed.append(module)

        if failed:
            raise click.ClickException(
                f"Cannot import modules from PYWORKFLOW_DISCOVER: {', '.join(failed)}. "
                f"Make sure the modules exist and are in your Python path."
            )
        return

    # Priority 3: pyworkflow.config.yaml
    yaml_config = _load_yaml_config()
    if yaml_config:
        # Support both 'module' (single) and 'modules' (list)
        modules: list[str] = []

        if "module" in yaml_config:
            modules.append(yaml_config["module"])
        if "modules" in yaml_config:
            modules.extend(yaml_config["modules"])

        if modules:
            logger.debug(f"Discovering from pyworkflow.config.yaml: {modules}")
            failed = []
            for module in modules:
                if not _import_module(module):
                    failed.append(module)

            if failed:
                project_root = _find_project_root()
                raise click.ClickException(
                    f"Cannot import modules from pyworkflow.config.yaml: {', '.join(failed)}. "
                    f"Make sure the modules exist and are in your Python path.\n"
                    f"  Current directory: {Path.cwd()}\n"
                    f"  Project root: {project_root or 'not found'}"
                )
            return

    # No discovery source found
    logger.debug("No workflow module specified")
