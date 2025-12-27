"""
Interactive prompt utilities using InquirerPy.

This module provides reusable prompt functions for interactive CLI workflows,
all styled with PyWorkflow branding.
"""

from pathlib import Path
from typing import Any, Callable

import click
from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from pyworkflow.cli.output.styles import PYWORKFLOW_STYLE


def confirm(message: str, default: bool = True) -> bool:
    """
    Display a yes/no confirmation prompt.

    Args:
        message: Question to ask the user
        default: Default answer if user just presses Enter

    Returns:
        True if user confirms, False otherwise

    Raises:
        click.Abort: If user presses Ctrl+C

    Example:
        >>> if confirm("Continue with setup?"):
        ...     print("Continuing...")
    """
    try:
        return inquirer.confirm(
            message=message,
            default=default,
            style=PYWORKFLOW_STYLE,
        ).execute()
    except KeyboardInterrupt:
        raise click.Abort()


def select(
    message: str,
    choices: list[str] | list[dict[str, str]],
    default: str | None = None,
) -> str:
    """
    Display a single-selection list.

    Args:
        message: Question to ask the user
        choices: List of options. Can be:
            - List of strings: ["option1", "option2"]
            - List of dicts: [{"name": "Display Text", "value": "value1"}]
        default: Default selected value

    Returns:
        Selected value

    Raises:
        click.Abort: If user presses Ctrl+C

    Example:
        >>> storage = select(
        ...     "Choose storage:",
        ...     choices=[
        ...         {"name": "SQLite (recommended)", "value": "sqlite"},
        ...         {"name": "File storage", "value": "file"}
        ...     ]
        ... )
    """
    try:
        # Convert string list to Choice objects
        if choices and isinstance(choices[0], str):
            choice_objects = [Choice(value=c, name=c) for c in choices]
        else:
            # Dict format: {"name": "...", "value": "..."}
            choice_objects = [
                Choice(value=c.get("value", c["name"]), name=c["name"])
                for c in choices
            ]

        return inquirer.select(
            message=message,
            choices=choice_objects,
            default=default,
            style=PYWORKFLOW_STYLE,
        ).execute()
    except KeyboardInterrupt:
        raise click.Abort()


def input_text(
    message: str,
    default: str = "",
    validate: Callable[[str], bool | str] | None = None,
) -> str:
    """
    Display a text input prompt.

    Args:
        message: Question or prompt text
        default: Default value if user just presses Enter
        validate: Optional validation function. Should return:
            - True if valid
            - False or error message string if invalid

    Returns:
        User's input text

    Raises:
        click.Abort: If user presses Ctrl+C

    Example:
        >>> def validate_module(value: str) -> bool | str:
        ...     if not value:
        ...         return True  # Empty is OK
        ...     if "." not in value:
        ...         return "Module path should contain dots (e.g., myapp.workflows)"
        ...     return True
        >>>
        >>> module = input_text(
        ...     "Workflow module path:",
        ...     default="myapp.workflows",
        ...     validate=validate_module
        ... )
    """
    try:
        return inquirer.text(
            message=message,
            default=default,
            validate=validate,
            style=PYWORKFLOW_STYLE,
        ).execute()
    except KeyboardInterrupt:
        raise click.Abort()


def filepath(
    message: str,
    default: str = "",
    only_directories: bool = False,
) -> str:
    """
    Display a filepath input prompt with tab completion.

    Args:
        message: Question or prompt text
        default: Default path value
        only_directories: If True, only allow directory paths

    Returns:
        Selected or entered file path

    Raises:
        click.Abort: If user presses Ctrl+C

    Example:
        >>> db_path = filepath(
        ...     "SQLite database path:",
        ...     default="./pyworkflow_data/pyworkflow.db"
        ... )
        >>>
        >>> data_dir = filepath(
        ...     "Data directory:",
        ...     default="./pyworkflow_data",
        ...     only_directories=True
        ... )
    """
    try:
        result = inquirer.filepath(
            message=message,
            default=default,
            only_directories=only_directories,
            style=PYWORKFLOW_STYLE,
        ).execute()

        # Convert to absolute path and resolve
        return str(Path(result).expanduser())
    except KeyboardInterrupt:
        raise click.Abort()


def multiselect(
    message: str,
    choices: list[str] | list[dict[str, str]],
    default: list[str] | None = None,
) -> list[str]:
    """
    Display a multi-selection checkbox list.

    Args:
        message: Question to ask the user
        choices: List of options. Can be:
            - List of strings: ["option1", "option2"]
            - List of dicts: [{"name": "Display Text", "value": "value1"}]
        default: List of default selected values

    Returns:
        List of selected values

    Raises:
        click.Abort: If user presses Ctrl+C

    Example:
        >>> features = multiselect(
        ...     "Select features to enable:",
        ...     choices=[
        ...         {"name": "Dashboard", "value": "dashboard"},
        ...         {"name": "Monitoring", "value": "monitoring"},
        ...         {"name": "Metrics", "value": "metrics"}
        ...     ],
        ...     default=["dashboard"]
        ... )
    """
    try:
        # Convert string list to Choice objects
        if choices and isinstance(choices[0], str):
            choice_objects = [
                Choice(value=c, name=c, enabled=(c in (default or [])))
                for c in choices
            ]
        else:
            # Dict format: {"name": "...", "value": "..."}
            choice_objects = [
                Choice(
                    value=c.get("value", c["name"]),
                    name=c["name"],
                    enabled=(c.get("value", c["name"]) in (default or [])),
                )
                for c in choices
            ]

        return inquirer.checkbox(
            message=message,
            choices=choice_objects,
            style=PYWORKFLOW_STYLE,
        ).execute()
    except KeyboardInterrupt:
        raise click.Abort()


def password(message: str, validate: Callable[[str], bool | str] | None = None) -> str:
    """
    Display a password input prompt (hidden text).

    Args:
        message: Question or prompt text
        validate: Optional validation function

    Returns:
        Entered password

    Raises:
        click.Abort: If user presses Ctrl+C

    Example:
        >>> def validate_password(value: str) -> bool | str:
        ...     if len(value) < 8:
        ...         return "Password must be at least 8 characters"
        ...     return True
        >>>
        >>> pwd = password("Enter password:", validate=validate_password)
    """
    try:
        return inquirer.secret(
            message=message,
            validate=validate,
            style=PYWORKFLOW_STYLE,
        ).execute()
    except KeyboardInterrupt:
        raise click.Abort()


# Validation helper functions

def validate_module_path(value: str) -> bool | str:
    """
    Validate Python module path.

    Args:
        value: Module path string (e.g., "myapp.workflows")

    Returns:
        True if valid, error message string if invalid

    Example:
        >>> validate_module_path("myapp.workflows")
        True
        >>> validate_module_path("invalid module")
        'Module path cannot contain spaces'
    """
    if not value:
        return True  # Empty is allowed

    if " " in value:
        return "Module path cannot contain spaces"

    if not all(part.isidentifier() for part in value.split(".")):
        return "Module path must be valid Python identifiers separated by dots"

    return True


def validate_nonempty(value: str) -> bool | str:
    """
    Validate that input is not empty.

    Args:
        value: Input string

    Returns:
        True if not empty, error message if empty
    """
    if not value or not value.strip():
        return "This field cannot be empty"
    return True


def validate_port(value: str) -> bool | str:
    """
    Validate port number.

    Args:
        value: Port number as string

    Returns:
        True if valid port (1-65535), error message otherwise
    """
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return True
        return "Port must be between 1 and 65535"
    except ValueError:
        return "Port must be a number"


def validate_url(value: str) -> bool | str:
    """
    Validate URL format.

    Args:
        value: URL string

    Returns:
        True if valid URL format, error message otherwise
    """
    if not value:
        return "URL cannot be empty"

    if not (value.startswith("http://") or value.startswith("https://")):
        return "URL must start with http:// or https://"

    return True
