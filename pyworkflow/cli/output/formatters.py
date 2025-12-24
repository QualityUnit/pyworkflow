"""Output formatting utilities using ANSI colors."""

import json
import sys
from datetime import datetime
from typing import Any

from pyworkflow.cli.output.styles import (
    BOLD,
    DIM,
    EVENT_COLORS,
    RESET,
    STATUS_COLORS,
    SYMBOLS,
    Colors,
)


def print_colored(text: str, color: str, bold: bool = False, file: Any = None) -> None:
    """
    Print text with ANSI color.

    Args:
        text: Text to print
        color: ANSI color code
        bold: Whether to make text bold
        file: Output file (default: stdout)
    """
    if file is None:
        file = sys.stdout
    prefix = f"{BOLD}" if bold else ""
    print(f"{prefix}{color}{text}{RESET}", file=file)


def print_breadcrumb(steps: list[str], current_index: int) -> None:
    """
    Print a breadcrumb navigation display.

    Args:
        steps: List of step names
        current_index: Index of the current step (0-based)

    Example:
        print_breadcrumb(["workflow", "arguments"], 1)
        # Output: workflow › arguments
    """
    parts = []
    for i, step in enumerate(steps):
        if i < current_index:
            # Completed step - dim
            parts.append(f"{DIM}{step}{RESET}")
        elif i == current_index:
            # Current step - primary color + bold
            parts.append(f"{Colors.PRIMARY}{BOLD}{step}{RESET}")
        else:
            # Future step - dim
            parts.append(f"{DIM}{step}{RESET}")

    breadcrumb = SYMBOLS["breadcrumb_sep"].join(parts)
    print(f"\n{breadcrumb}\n")


def print_list(
    items: list[dict[str, Any]],
    title: str | None = None,
    key_field: str = "name",
    detail_fields: list[str] | None = None,
) -> None:
    """
    Print items as a simple indented list.

    Args:
        items: List of dictionaries to display
        title: Optional header title
        key_field: Primary field to display for each item
        detail_fields: Additional fields to show indented below each item
    """
    if title:
        print(f"\n{Colors.PRIMARY}{BOLD}{title}{RESET}\n")

    if not items:
        print(f"  {DIM}No items to display{RESET}")
        return

    for item in items:
        # Print main item
        name = item.get(key_field, "Unknown")
        print(f"  {Colors.bold(name)}")

        # Print detail fields if provided
        if detail_fields:
            for field in detail_fields:
                if field in item and item[field]:
                    value = item[field]
                    # Format status specially
                    if field.lower() == "status":
                        color = STATUS_COLORS.get(str(value).lower(), "")
                        value = f"{color}{value}{RESET}"
                    label = field.replace("_", " ").title()
                    print(f"    {DIM}{label}:{RESET} {value}")

        print()  # Blank line between items


def format_key_value(
    data: dict[str, Any],
    title: str | None = None,
) -> None:
    """
    Print key-value pairs with formatting.

    Args:
        data: Dictionary of key-value pairs
        title: Optional title
    """
    if title:
        print(f"\n{Colors.PRIMARY}{BOLD}{title}{RESET}\n")

    for key, value in data.items():
        # Format value based on type
        if isinstance(value, datetime):
            value_str = value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, dict):
            value_str = json.dumps(value, indent=2)
        elif value is None:
            value_str = f"{DIM}None{RESET}"
        else:
            value_str = str(value)

        # Apply special formatting for status
        if key.lower() == "status":
            color = STATUS_COLORS.get(value_str.lower(), "")
            value_str = f"{color}{value_str}{RESET}"

        print(f"  {Colors.CYAN}{key}:{RESET} {value_str}")


def format_json(data: Any, indent: int = 2) -> None:
    """
    Print data as formatted JSON.

    Args:
        data: Data to format as JSON
        indent: JSON indentation level
    """
    json_str = json.dumps(data, indent=indent, default=str)
    print(json_str)


def format_plain(data: list[str]) -> None:
    """
    Print data as plain text (one item per line).

    Args:
        data: List of strings to print
    """
    for item in data:
        print(item)


def format_status(status: str) -> str:
    """
    Return status string with ANSI color.

    Args:
        status: Status string

    Returns:
        Colored status string
    """
    color = STATUS_COLORS.get(status.lower(), "")
    return f"{color}{status}{RESET}"


def format_event_type(event_type: str) -> str:
    """
    Return event type string with ANSI color.

    Args:
        event_type: Event type string

    Returns:
        Colored event type string
    """
    color = EVENT_COLORS.get(event_type.lower(), "")
    return f"{color}{event_type}{RESET}"


def print_success(message: str) -> None:
    """Print success message with green checkmark."""
    print(f"{Colors.GREEN}{SYMBOLS['success']}{RESET} {message}")


def print_error(message: str) -> None:
    """Print error message with red X to stderr."""
    print(f"{Colors.RED}{SYMBOLS['error']}{RESET} {message}", file=sys.stderr)


def print_warning(message: str) -> None:
    """Print warning message with yellow warning symbol."""
    print(f"{Colors.YELLOW}{SYMBOLS['warning']}{RESET} {message}")


def print_info(message: str) -> None:
    """Print info message with blue info symbol."""
    print(f"{Colors.PRIMARY}{SYMBOLS['info']}{RESET} {message}")


def clear_line() -> None:
    """Clear the current terminal line."""
    sys.stdout.write("\033[2K\r")
    sys.stdout.flush()


def move_cursor_up(lines: int = 1) -> None:
    """Move cursor up N lines."""
    sys.stdout.write(f"\033[{lines}A")
    sys.stdout.flush()


def hide_cursor() -> None:
    """Hide the terminal cursor."""
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()


def show_cursor() -> None:
    """Show the terminal cursor."""
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()


# Deprecated aliases for backwards compatibility during transition
def format_table(
    data: list[dict[str, Any]],
    columns: list[str],
    title: str | None = None,
) -> None:
    """
    Format data as a simple list (replacing Rich tables).

    Args:
        data: List of dictionaries containing row data
        columns: List of column names to display
        title: Optional table title
    """
    if title:
        print(f"\n{Colors.PRIMARY}{BOLD}{title}{RESET}\n")

    if not data:
        print(f"  {DIM}No data to display{RESET}")
        return

    for row in data:
        # Print first column as the main item (bold)
        first_col = columns[0] if columns else None
        if first_col and first_col in row:
            print(f"  {Colors.bold(str(row[first_col]))}")

        # Print remaining columns as details
        for col in columns[1:]:
            if col in row:
                value = row[col]
                # Format status specially
                if col.lower() == "status":
                    value = format_status(str(value))
                print(f"    {DIM}{col}:{RESET} {value}")

        print()  # Blank line between items


def format_panel(
    content: str,
    title: str | None = None,
    border_style: str = "blue",
) -> None:
    """
    Print content with a simple title header (replacing Rich panels).

    Args:
        content: Content to display
        title: Optional title
        border_style: Ignored (kept for compatibility)
    """
    if title:
        print(f"\n{Colors.PRIMARY}{BOLD}{title}{RESET}")
        print(f"{DIM}{'─' * len(title)}{RESET}")
    print(content)


def format_tree(data: dict[str, Any], title: str = "Data") -> None:
    """
    Print data as an indented tree structure.

    Args:
        data: Nested dictionary to display
        title: Tree root title
    """
    print(f"\n{Colors.bold(title)}")
    _print_tree_nodes(data, indent=2)


def _print_tree_nodes(data: Any, indent: int = 0) -> None:
    """Helper to recursively print tree nodes."""
    prefix = " " * indent
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict | list):
                print(f"{prefix}{Colors.CYAN}{key}{RESET}:")
                _print_tree_nodes(value, indent + 2)
            else:
                print(f"{prefix}{Colors.CYAN}{key}:{RESET} {value}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict | list):
                print(f"{prefix}{DIM}{i}:{RESET}")
                _print_tree_nodes(item, indent + 2)
            else:
                print(f"{prefix}{DIM}{i}:{RESET} {item}")
    else:
        print(f"{prefix}{data}")
