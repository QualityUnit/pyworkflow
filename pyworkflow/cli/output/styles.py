"""Rich styles and themes for CLI output."""

from rich.theme import Theme

# Custom theme for PyWorkflow CLI
PYWORKFLOW_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "workflow": "magenta",
    "step": "blue",
    "status.completed": "green",
    "status.running": "blue",
    "status.suspended": "yellow",
    "status.failed": "red",
    "status.cancelled": "magenta",
    "status.pending": "cyan",
})
