"""Workflow discovery utilities."""

import importlib
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from loguru import logger


def discover_workflows(
    module_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Import Python module to trigger workflow registration.

    Workflows are registered when their module is imported, as the @workflow
    decorator registers them in the global registry. This function handles
    importing the appropriate module based on configuration priority.

    Priority:
    1. Explicit module_path argument (from --module flag)
    2. PYWORKFLOW_MODULE env var (handled by Click)
    3. Config file module setting
    4. Auto-discovery from current directory

    Args:
        module_path: Explicit module path to import
        config: Configuration dict from pyworkflow.toml

    Examples:
        # Explicit module
        discover_workflows("myapp.workflows")

        # From config
        discover_workflows(config={"module": "myapp.workflows"})

        # Auto-discovery
        discover_workflows()  # Will try to import current directory
    """
    # Priority 1: Explicit module path
    if module_path:
        logger.debug(f"Importing workflows from explicit module: {module_path}")
        try:
            importlib.import_module(module_path)
            logger.info(f"Successfully imported module: {module_path}")
            return
        except ModuleNotFoundError as e:
            logger.error(f"Failed to import module '{module_path}': {e}")
            raise click.ClickException(
                f"Cannot import module '{module_path}'. "
                f"Make sure the module exists and is in your Python path."
            ) from e

    # Priority 2: Config file module setting
    if config and config.get("module"):
        module = config["module"]
        logger.debug(f"Importing workflows from config module: {module}")
        try:
            importlib.import_module(module)
            logger.info(f"Successfully imported module from config: {module}")
            return
        except ModuleNotFoundError as e:
            logger.error(f"Failed to import module '{module}' from config: {e}")
            raise click.ClickException(
                f"Cannot import module '{module}' specified in config file. "
                f"Make sure the module exists and is in your Python path."
            ) from e

    # Priority 3: Auto-discovery from current directory
    cwd = Path.cwd()
    logger.debug(f"Attempting auto-discovery from current directory: {cwd}")

    # Check if current directory is a Python package
    if (cwd / "__init__.py").exists():
        parent_path = str(cwd.parent)
        if parent_path not in sys.path:
            sys.path.insert(0, parent_path)

        package_name = cwd.name
        logger.debug(f"Auto-discovered package: {package_name}")
        try:
            importlib.import_module(package_name)
            logger.info(f"Successfully auto-imported package: {package_name}")
            return
        except ModuleNotFoundError as e:
            logger.warning(f"Failed to auto-import package '{package_name}': {e}")
            # Fall through - this is not a fatal error for auto-discovery

    # If we get here, no module was imported
    logger.debug("No workflow module specified or auto-discovered")


# Import click here at the bottom to avoid circular imports
import click
