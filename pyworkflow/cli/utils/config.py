"""Configuration file loading utilities."""

import tomllib
from pathlib import Path
from typing import Any

from loguru import logger


def find_config_file() -> Path | None:
    """
    Find configuration file in current directory or parents.

    Searches for configuration files in this order:
    1. pyworkflow.toml
    2. .pyworkflow.toml
    3. pyproject.toml (with [tool.pyworkflow] section)

    The search starts in the current directory and walks up the directory
    tree until a config file is found or the root is reached.

    Returns:
        Path to config file if found, None otherwise

    Examples:
        config_path = find_config_file()
        if config_path:
            print(f"Found config at: {config_path}")
    """
    current = Path.cwd()

    # Walk up the directory tree
    for path in [current] + list(current.parents):
        # Check for dedicated pyworkflow config files
        for name in ["pyworkflow.toml", ".pyworkflow.toml"]:
            config_path = path / name
            if config_path.exists():
                logger.debug(f"Found config file: {config_path}")
                return config_path

        # Check for pyproject.toml with [tool.pyworkflow] section
        pyproject = path / "pyproject.toml"
        if pyproject.exists():
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                if "tool" in data and "pyworkflow" in data["tool"]:
                    logger.debug(f"Found pyworkflow config in pyproject.toml: {pyproject}")
                    return pyproject
            except Exception as e:
                logger.warning(f"Failed to parse pyproject.toml at {pyproject}: {e}")

    logger.debug("No config file found")
    return None


def load_config() -> dict[str, Any]:
    """
    Load CLI configuration from file.

    Searches for and loads configuration from pyworkflow.toml,
    .pyworkflow.toml, or pyproject.toml files.

    Returns:
        Configuration dictionary. Returns empty dict if no config file found.

    Examples:
        config = load_config()
        module = config.get("module")
        storage_type = config.get("storage", {}).get("type")
    """
    config_path = find_config_file()
    if not config_path:
        logger.debug("No configuration file found, using defaults")
        return {}

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        logger.info(f"Loaded configuration from: {config_path}")

        # Handle pyproject.toml format
        if config_path.name == "pyproject.toml":
            config = data.get("tool", {}).get("pyworkflow", {})
        else:
            # For dedicated pyworkflow.toml files, get the pyworkflow section
            config = data.get("pyworkflow", data)

        logger.debug(f"Configuration loaded: {config}")
        return config

    except Exception as e:
        logger.error(f"Failed to load configuration from {config_path}: {e}")
        return {}


def get_config_value(
    config: dict[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    """
    Get nested configuration value.

    Args:
        config: Configuration dictionary
        *keys: Sequence of keys to traverse
        default: Default value if key path doesn't exist

    Returns:
        Configuration value or default

    Examples:
        config = {"storage": {"type": "file", "base_path": "./data"}}

        # Get nested value
        storage_type = get_config_value(config, "storage", "type")  # "file"

        # With default
        timeout = get_config_value(config, "timeout", default=30)  # 30
    """
    value: Any = config
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
            if value is None:
                return default
        else:
            return default
    return value if value is not None else default
