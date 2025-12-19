"""Output formatting utilities using Rich."""

import json
from typing import Any, List, Dict, Optional
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax
from rich.panel import Panel
from rich.tree import Tree
from rich import box

console = Console()


def format_table(
    data: List[Dict[str, Any]],
    columns: List[str],
    title: Optional[str] = None,
) -> None:
    """
    Format and print data as a Rich table.

    Args:
        data: List of dictionaries containing row data
        columns: List of column names to display
        title: Optional table title

    Examples:
        data = [
            {"name": "my_workflow", "status": "completed"},
            {"name": "other_workflow", "status": "running"},
        ]
        format_table(data, ["name", "status"], title="Workflows")
    """
    if not data:
        console.print("[dim]No data to display[/dim]")
        return

    table = Table(
        title=title,
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED,
    )

    # Add columns
    for col in columns:
        table.add_column(col, style="cyan")

    # Add rows
    for row in data:
        cells = []
        for col in columns:
            value = row.get(col, "")

            # Apply special formatting for certain column types
            if col.lower() == "status":
                value = format_status(str(value))
            elif isinstance(value, datetime):
                value = value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                value = str(value)

            cells.append(value)

        table.add_row(*cells)

    console.print(table)


def format_json(data: Any, indent: int = 2) -> None:
    """
    Format and print data as JSON with syntax highlighting.

    Args:
        data: Data to format as JSON
        indent: JSON indentation level

    Examples:
        data = {"run_id": "run_123", "status": "completed"}
        format_json(data)
    """
    json_str = json.dumps(data, indent=indent, default=str)
    syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)
    console.print(syntax)


def format_plain(data: List[str]) -> None:
    """
    Format and print data as plain text (one item per line).

    Args:
        data: List of strings to print

    Examples:
        data = ["run_123", "run_456", "run_789"]
        format_plain(data)
    """
    for item in data:
        console.print(item)


def format_status(status: str) -> str:
    """
    Colorize workflow/run status.

    Args:
        status: Status string

    Returns:
        Rich-formatted status string with color

    Examples:
        >>> format_status("completed")
        '[green]completed[/green]'
    """
    colors = {
        "completed": "green",
        "running": "blue",
        "suspended": "yellow",
        "failed": "red",
        "cancelled": "magenta",
        "pending": "cyan",
    }
    color = colors.get(status.lower(), "white")
    return f"[{color}]{status}[/{color}]"


def format_panel(
    content: str,
    title: Optional[str] = None,
    border_style: str = "blue",
) -> None:
    """
    Format and print content in a Rich panel.

    Args:
        content: Content to display in panel
        title: Optional panel title
        border_style: Border color/style

    Examples:
        format_panel("Workflow completed successfully!", title="Success", border_style="green")
    """
    panel = Panel(content, title=title, border_style=border_style, box=box.ROUNDED)
    console.print(panel)


def format_key_value(data: Dict[str, Any], title: Optional[str] = None) -> None:
    """
    Format and print key-value pairs.

    Args:
        data: Dictionary of key-value pairs
        title: Optional title

    Examples:
        data = {"run_id": "run_123", "workflow": "my_workflow", "status": "completed"}
        format_key_value(data, title="Workflow Run")
    """
    if title:
        console.print(f"\n[bold magenta]{title}[/bold magenta]")

    for key, value in data.items():
        # Format value
        if isinstance(value, datetime):
            value_str = value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, dict):
            value_str = json.dumps(value, indent=2)
        elif value is None:
            value_str = "[dim]None[/dim]"
        else:
            value_str = str(value)

        # Apply special formatting for status
        if key.lower() == "status":
            value_str = format_status(value_str)

        console.print(f"  [cyan]{key}:[/cyan] {value_str}")


def format_tree(data: Dict[str, Any], title: str = "Data") -> None:
    """
    Format and print data as a tree structure.

    Args:
        data: Nested dictionary to display as tree
        title: Tree root title

    Examples:
        data = {
            "workflow": {"name": "my_workflow", "status": "completed"},
            "steps": ["step1", "step2"]
        }
        format_tree(data, title="Workflow Details")
    """
    tree = Tree(f"[bold]{title}[/bold]")
    _add_tree_nodes(tree, data)
    console.print(tree)


def _add_tree_nodes(tree: Tree, data: Any) -> None:
    """Helper to recursively add nodes to tree."""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                branch = tree.add(f"[cyan]{key}[/cyan]")
                _add_tree_nodes(branch, value)
            else:
                tree.add(f"[cyan]{key}:[/cyan] {value}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, (dict, list)):
                branch = tree.add(f"[dim]{i}[/dim]")
                _add_tree_nodes(branch, item)
            else:
                tree.add(f"[dim]{i}:[/dim] {item}")
    else:
        tree.add(str(data))


def print_success(message: str) -> None:
    """Print success message."""
    console.print(f"[green]✓[/green] {message}")


def print_error(message: str) -> None:
    """Print error message."""
    console.print(f"[red]✗[/red] {message}", err=True)


def print_warning(message: str) -> None:
    """Print warning message."""
    console.print(f"[yellow]⚠[/yellow] {message}")


def print_info(message: str) -> None:
    """Print info message."""
    console.print(f"[blue]ℹ[/blue] {message}")
