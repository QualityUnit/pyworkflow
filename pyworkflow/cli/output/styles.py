"""Styles and themes for PyWorkflow CLI using InquirerPy."""

from InquirerPy.utils import get_style

# Primary brand color
PRIMARY_COLOR = "#1c64fd"

# InquirerPy style configuration
PYWORKFLOW_STYLE = get_style(
    {
        "questionmark": f"{PRIMARY_COLOR} bold",
        "answermark": PRIMARY_COLOR,
        "answer": f"{PRIMARY_COLOR} bold",
        "pointer": f"{PRIMARY_COLOR} bold",
        "checkbox": PRIMARY_COLOR,
        "marker": PRIMARY_COLOR,
        "question": "",
        "instruction": "italic #666666",
        "input": PRIMARY_COLOR,
        "fuzzy_prompt": PRIMARY_COLOR,
        "fuzzy_match": f"{PRIMARY_COLOR} bold",
    },
    style_override=False,
)

# ANSI color codes for terminal output
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"


class Colors:
    """ANSI color codes for CLI output."""

    # Primary brand color (approximated in ANSI - bright blue)
    PRIMARY = "\033[38;2;28;100;253m"  # RGB: #1c64fd

    # Status colors
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    # Bright variants
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"

    @classmethod
    def reset(cls) -> str:
        return RESET

    @classmethod
    def bold(cls, text: str) -> str:
        return f"{BOLD}{text}{RESET}"

    @classmethod
    def dim(cls, text: str) -> str:
        return f"{DIM}{text}{RESET}"

    @classmethod
    def italic(cls, text: str) -> str:
        return f"{ITALIC}{text}{RESET}"


# Status color mapping
STATUS_COLORS: dict[str, str] = {
    "completed": Colors.GREEN,
    "running": Colors.BLUE,
    "suspended": Colors.YELLOW,
    "failed": Colors.RED,
    "cancelled": Colors.MAGENTA,
    "pending": Colors.CYAN,
    # Hook statuses
    "received": Colors.GREEN,
    "expired": Colors.RED,
    "disposed": Colors.GRAY,
}

# Event type color mapping
EVENT_COLORS: dict[str, str] = {
    "workflow_started": Colors.BLUE,
    "workflow_completed": Colors.GREEN,
    "workflow_failed": Colors.RED,
    "workflow_cancelled": Colors.RED,
    "workflow_interrupted": Colors.RED,
    "step_started": Colors.CYAN,
    "step_completed": Colors.GREEN,
    "step_failed": Colors.RED,
    "step_cancelled": Colors.RED,
    "step_retrying": Colors.YELLOW,
    "sleep_started": Colors.MAGENTA,
    "sleep_completed": Colors.MAGENTA,
    "hook_created": Colors.YELLOW,
    "hook_received": Colors.GREEN,
    "cancellation_requested": Colors.RED,
    "cancellation.requested": Colors.RED,
}

# Spinner frames for watch mode
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# UI symbols
SYMBOLS = {
    "pointer": "❯",
    "success": "✓",
    "error": "✗",
    "warning": "⚠",
    "info": "ℹ",
    "bullet": "•",
    "arrow": "→",
    "breadcrumb_sep": " › ",
    "checkbox_on": "◉",
    "checkbox_off": "○",
}
