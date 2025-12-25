"""Workflow management commands."""

import asyncio
import inspect
import json
import sys
import threading
import time
from datetime import datetime
from typing import Any, get_type_hints

import click
from InquirerPy import inquirer

import pyworkflow
from pyworkflow import RunStatus
from pyworkflow.cli.output.formatters import (
    clear_line,
    format_event_type,
    format_json,
    format_key_value,
    format_plain,
    format_table,
    hide_cursor,
    move_cursor_up,
    print_breadcrumb,
    print_error,
    print_info,
    print_success,
    print_warning,
    show_cursor,
)
from pyworkflow.cli.output.styles import (
    DIM,
    PYWORKFLOW_STYLE,
    RESET,
    SPINNER_FRAMES,
    SYMBOLS,
    Colors,
)
from pyworkflow.cli.utils.async_helpers import async_command
from pyworkflow.cli.utils.discovery import discover_workflows
from pyworkflow.cli.utils.storage import create_storage


def _build_workflow_choices(workflows_dict: dict[str, Any]) -> list[dict[str, str]]:
    """Build choices list for workflow selection."""
    choices = []
    for name, meta in workflows_dict.items():
        description = ""
        if meta.original_func.__doc__:
            # Get first line of docstring
            description = meta.original_func.__doc__.strip().split("\n")[0][:50]

        display_name = f"{name} - {description}" if description else name

        choices.append({"name": display_name, "value": name})
    return choices


def _select_workflow(workflows_dict: dict[str, Any]) -> str | None:
    """
    Display an interactive workflow selection menu using InquirerPy (sync version).

    Args:
        workflows_dict: Dictionary of workflow name -> WorkflowMetadata

    Returns:
        Selected workflow name or None if cancelled
    """
    if not workflows_dict:
        print_error("No workflows registered")
        return None

    choices = _build_workflow_choices(workflows_dict)

    try:
        result = inquirer.select(
            message="Select workflow",
            choices=choices,
            style=PYWORKFLOW_STYLE,
            pointer=SYMBOLS["pointer"],
            qmark="?",
            amark=SYMBOLS["success"],
        ).execute()
        return result
    except KeyboardInterrupt:
        print(f"\n{DIM}Cancelled{RESET}")
        return None


async def _select_workflow_async(workflows_dict: dict[str, Any]) -> str | None:
    """
    Display an interactive workflow selection menu using InquirerPy (async version).

    Args:
        workflows_dict: Dictionary of workflow name -> WorkflowMetadata

    Returns:
        Selected workflow name or None if cancelled
    """
    if not workflows_dict:
        print_error("No workflows registered")
        return None

    choices = _build_workflow_choices(workflows_dict)

    try:
        result = await inquirer.select(  # type: ignore[func-returns-value]
            message="Select workflow",
            choices=choices,
            style=PYWORKFLOW_STYLE,
            pointer=SYMBOLS["pointer"],
            qmark="?",
            amark=SYMBOLS["success"],
        ).execute_async()
        return result
    except KeyboardInterrupt:
        print(f"\n{DIM}Cancelled{RESET}")
        return None


def _get_workflow_parameters(func: Any) -> list[dict[str, Any]]:
    """
    Extract parameter information from a workflow function.

    Args:
        func: The workflow function to inspect

    Returns:
        List of parameter dicts with name, type, default, and required info
    """
    sig = inspect.signature(func)
    params = []

    # Try to get type hints
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    for param_name, param in sig.parameters.items():
        # Skip *args and **kwargs
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        param_info = {
            "name": param_name,
            "type": hints.get(param_name, Any),
            "has_default": param.default is not inspect.Parameter.empty,
            "default": param.default if param.default is not inspect.Parameter.empty else None,
            "required": param.default is inspect.Parameter.empty,
        }
        params.append(param_info)

    return params


def _get_type_name(type_hint: Any) -> str:
    """Get a human-readable name for a type hint."""
    if type_hint is Any:
        return "any"
    if hasattr(type_hint, "__name__"):
        return type_hint.__name__
    return str(type_hint)


def _parse_value(value_str: str, type_hint: Any) -> Any:
    """
    Parse a string value to the appropriate type.

    Args:
        value_str: The string value from user input
        type_hint: The expected type

    Returns:
        Parsed value
    """
    if not value_str:
        return None

    # Handle common types
    if type_hint is bool or (hasattr(type_hint, "__name__") and type_hint.__name__ == "bool"):
        return value_str.lower() in ("true", "1", "yes", "y")

    if type_hint is int or (hasattr(type_hint, "__name__") and type_hint.__name__ == "int"):
        return int(value_str)

    if type_hint is float or (hasattr(type_hint, "__name__") and type_hint.__name__ == "float"):
        return float(value_str)

    # Try JSON parsing for complex types (lists, dicts, etc.)
    try:
        return json.loads(value_str)
    except json.JSONDecodeError:
        # Return as string
        return value_str


def _prompt_for_arguments(params: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Interactively prompt user for workflow argument values using InquirerPy (sync).

    Args:
        params: List of parameter info dicts

    Returns:
        Dictionary of argument name -> value
    """
    if not params:
        return {}

    kwargs = {}

    for param in params:
        name = param["name"]
        type_hint = param["type"]
        has_default = param["has_default"]
        default = param["default"]
        required = param["required"]

        type_name = _get_type_name(type_hint)

        # Build instruction text
        if required:
            instruction = f"({type_name})"
        else:
            default_display = repr(default) if default is not None else "None"
            instruction = f"({type_name}, default={default_display})"

        try:
            # Handle boolean type with confirm prompt
            if type_hint is bool or (
                hasattr(type_hint, "__name__") and type_hint.__name__ == "bool"
            ):
                default_val = default if has_default else False
                value = inquirer.confirm(
                    message=name,
                    default=default_val,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                ).execute()
                kwargs[name] = value

            # Handle int type with number prompt
            elif type_hint is int or (
                hasattr(type_hint, "__name__") and type_hint.__name__ == "int"
            ):
                # InquirerPy number prompt needs a valid number or None, not empty string
                default_val = default if has_default and default is not None else None
                value_str = inquirer.number(
                    message=name,
                    default=default_val,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                    float_allowed=False,
                ).execute()
                if value_str is not None:
                    kwargs[name] = int(value_str)
                elif has_default:
                    kwargs[name] = default

            # Handle float type with number prompt
            elif type_hint is float or (
                hasattr(type_hint, "__name__") and type_hint.__name__ == "float"
            ):
                # InquirerPy number prompt needs a valid number or None, not empty string
                default_val = default if has_default and default is not None else None
                value_str = inquirer.number(
                    message=name,
                    default=default_val,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                    float_allowed=True,
                ).execute()
                if value_str is not None:
                    kwargs[name] = float(value_str)
                elif has_default:
                    kwargs[name] = default

            # Handle string/other types with text prompt
            else:
                if has_default and default is not None:
                    default_str = json.dumps(default) if not isinstance(default, str) else default
                else:
                    default_str = ""

                value_str = inquirer.text(
                    message=name,
                    default=default_str,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                    mandatory=required,
                ).execute()

                if value_str == "" and has_default:
                    kwargs[name] = default
                elif value_str == "" and not required:
                    # Skip optional params with no input
                    continue
                elif value_str is not None:
                    kwargs[name] = _parse_value(value_str, type_hint)

        except KeyboardInterrupt:
            print(f"\n{DIM}Cancelled{RESET}")
            raise click.Abort()

    return kwargs


async def _prompt_for_arguments_async(params: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Interactively prompt user for workflow argument values using InquirerPy (async).

    Args:
        params: List of parameter info dicts

    Returns:
        Dictionary of argument name -> value
    """
    if not params:
        return {}

    kwargs: dict[str, Any] = {}

    for param in params:
        name = param["name"]
        type_hint = param["type"]
        has_default = param["has_default"]
        default = param["default"]
        required = param["required"]

        type_name = _get_type_name(type_hint)

        # Build instruction text
        if required:
            instruction = f"({type_name})"
        else:
            default_display = repr(default) if default is not None else "None"
            instruction = f"({type_name}, default={default_display})"

        try:
            # Handle boolean type with confirm prompt
            if type_hint is bool or (
                hasattr(type_hint, "__name__") and type_hint.__name__ == "bool"
            ):
                default_val = default if has_default else False
                value = await inquirer.confirm(  # type: ignore[func-returns-value]
                    message=name,
                    default=default_val,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                ).execute_async()
                kwargs[name] = value

            # Handle int type with number prompt
            elif type_hint is int or (
                hasattr(type_hint, "__name__") and type_hint.__name__ == "int"
            ):
                # InquirerPy number prompt needs a valid number or None, not empty string
                default_val = default if has_default and default is not None else None
                value_str = await inquirer.number(  # type: ignore[func-returns-value]
                    message=name,
                    default=default_val,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                    float_allowed=False,
                ).execute_async()
                if value_str is not None:
                    kwargs[name] = int(value_str)
                elif has_default:
                    kwargs[name] = default

            # Handle float type with number prompt
            elif type_hint is float or (
                hasattr(type_hint, "__name__") and type_hint.__name__ == "float"
            ):
                # InquirerPy number prompt needs a valid number or None, not empty string
                default_val = default if has_default and default is not None else None
                value_str = await inquirer.number(  # type: ignore[func-returns-value]
                    message=name,
                    default=default_val,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                    float_allowed=True,
                ).execute_async()
                if value_str is not None:
                    kwargs[name] = float(value_str)
                elif has_default:
                    kwargs[name] = default

            # Handle string/other types with text prompt
            else:
                if has_default and default is not None:
                    default_str = json.dumps(default) if not isinstance(default, str) else default
                else:
                    default_str = ""

                value_str = await inquirer.text(  # type: ignore[func-returns-value]
                    message=name,
                    default=default_str,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                    mandatory=required,
                ).execute_async()

                if value_str == "" and has_default:
                    kwargs[name] = default
                elif value_str == "" and not required:
                    # Skip optional params with no input
                    continue
                elif value_str is not None:
                    kwargs[name] = _parse_value(value_str, type_hint)

        except KeyboardInterrupt:
            print(f"\n{DIM}Cancelled{RESET}")
            raise click.Abort()

    return kwargs


class SpinnerDisplay:
    """ANSI-based spinner display for watch mode."""

    def __init__(self, message: str = "Running", detail_mode: bool = False):
        self.message = message
        self.running = False
        self.frame_index = 0
        self.thread: threading.Thread | None = None
        self.events: list[Any] = []
        self.status: RunStatus = RunStatus.RUNNING
        self.elapsed: float = 0.0
        self.lines_printed = 0
        self.detail_mode = detail_mode
        self._lock = threading.Lock()
        self._setup_keyboard_listener()

    def _setup_keyboard_listener(self) -> None:
        """Setup keyboard listener for Ctrl+O toggle."""
        self._original_settings = None
        self._stdin_fd = None
        self._keyboard_active = False

        try:
            import termios

            self._stdin_fd = sys.stdin.fileno()
            self._original_settings = termios.tcgetattr(self._stdin_fd)

            # Set up non-canonical mode with echo disabled
            new_settings = termios.tcgetattr(self._stdin_fd)
            # Disable canonical mode (ICANON) and echo (ECHO)
            new_settings[3] = new_settings[3] & ~(termios.ICANON | termios.ECHO)
            # Set minimum characters to read to 0 (non-blocking)
            new_settings[6][termios.VMIN] = 0
            new_settings[6][termios.VTIME] = 0
            termios.tcsetattr(self._stdin_fd, termios.TCSANOW, new_settings)
            self._keyboard_active = True
        except Exception:
            # Not a terminal or termios not available
            pass

    def _check_keyboard(self) -> None:
        """Check for keyboard input (Ctrl+O)."""
        if not self._keyboard_active:
            return

        try:
            import select

            # Check if input is available (non-blocking)
            if select.select([sys.stdin], [], [], 0)[0]:
                char = sys.stdin.read(1)
                if char:
                    # Ctrl+O is ASCII 15
                    if ord(char) == 15:
                        with self._lock:
                            self.detail_mode = not self.detail_mode
        except Exception:
            pass

    def _restore_terminal(self) -> None:
        """Restore original terminal settings."""
        if self._original_settings and self._stdin_fd is not None:
            try:
                import termios

                termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, self._original_settings)
            except Exception:
                pass
            self._keyboard_active = False

    def _format_step_call(self, event_data: dict[str, Any]) -> str:
        """Format step call with arguments like: step_name(arg1, arg2, ...)"""
        step_name = event_data.get("step_name", "unknown")

        # Collect arguments
        args_parts = []

        # Check for args (positional)
        if "args" in event_data and event_data["args"]:
            args = event_data["args"]
            if isinstance(args, list | tuple):
                for arg in args:
                    arg_str = self._format_value_short(arg)
                    args_parts.append(arg_str)
            else:
                args_parts.append(self._format_value_short(args))

        # Check for kwargs
        if "kwargs" in event_data and event_data["kwargs"]:
            kwargs = event_data["kwargs"]
            if isinstance(kwargs, dict):
                for k, v in kwargs.items():
                    val_str = self._format_value_short(v)
                    args_parts.append(f"{k}={val_str}")

        # Build the call signature (show all args, values are already shortened)
        if args_parts:
            args_str = ", ".join(args_parts)
            return f"{step_name}({args_str})"
        else:
            return f"{step_name}()"

    def _format_value_short(self, value: Any) -> str:
        """Format a value for short display."""
        if value is None:
            return "None"
        if isinstance(value, str):
            if len(value) > 15:
                return f'"{value[:12]}..."'
            return f'"{value}"'
        if isinstance(value, int | float | bool):
            return str(value)
        if isinstance(value, dict):
            return "{...}"
        if isinstance(value, list | tuple):
            return "[...]"
        return str(value)[:15]

    def _format_value_full(self, value: Any) -> str:
        """Format a value for full display (no truncation)."""
        if value is None:
            return "None"
        if isinstance(value, str):
            return f'"{value}"'
        if isinstance(value, int | float | bool):
            return str(value)
        if isinstance(value, dict | list | tuple):
            return json.dumps(value, default=str)
        return str(value)

    def _format_step_call_full(self, event_data: dict[str, Any]) -> str:
        """Format step call with full arguments (no truncation)."""
        step_name = event_data.get("step_name", "unknown")

        # Collect arguments
        args_parts = []

        # Check for args (positional)
        if "args" in event_data and event_data["args"]:
            args = event_data["args"]
            if isinstance(args, list | tuple):
                for arg in args:
                    arg_str = self._format_value_full(arg)
                    args_parts.append(arg_str)
            else:
                args_parts.append(self._format_value_full(args))

        # Check for kwargs
        if "kwargs" in event_data and event_data["kwargs"]:
            kwargs = event_data["kwargs"]
            if isinstance(kwargs, dict):
                for k, v in kwargs.items():
                    val_str = self._format_value_full(v)
                    args_parts.append(f"{k}={val_str}")

        # Build the call signature (no truncation)
        if args_parts:
            args_str = ", ".join(args_parts)
            return f"{step_name}({args_str})"
        else:
            return f"{step_name}()"

    def _format_event_detail(self, event: Any) -> list[str]:
        """Format event with full details for detail mode (no truncation)."""
        lines = []
        time_str = event.timestamp.strftime("%H:%M:%S.%f")[:-3] if event.timestamp else "--:--:--"
        event_type = format_event_type(event.type.value)

        # Main event line
        lines.append(f"  {DIM}{time_str}{RESET} {event_type}")

        if event.data:
            # Show step call signature for step events (full arguments)
            if "step_name" in event.data:
                step_call = self._format_step_call_full(event.data)
                lines.append(f"           {Colors.CYAN}{step_call}{RESET}")

            # Show result if present (for completed events) - no truncation
            if "result" in event.data:
                result = event.data["result"]
                result_str = (
                    json.dumps(result, default=str, indent=2)
                    if not isinstance(result, str)
                    else result
                )
                # Handle multi-line results with proper indentation
                result_lines = result_str.split("\n")
                if len(result_lines) == 1:
                    lines.append(f"           {Colors.GREEN}result:{RESET} {result_str}")
                else:
                    lines.append(f"           {Colors.GREEN}result:{RESET}")
                    for rline in result_lines:
                        lines.append(f"             {rline}")

            # Show error if present - no truncation
            if "error" in event.data:
                error_str = str(event.data["error"])
                error_lines = error_str.split("\n")
                if len(error_lines) == 1:
                    lines.append(f"           {Colors.RED}error:{RESET} {error_str}")
                else:
                    lines.append(f"           {Colors.RED}error:{RESET}")
                    for eline in error_lines:
                        lines.append(f"             {eline}")

            # Show other relevant fields - no truncation
            for key, value in event.data.items():
                if key in ("step_name", "result", "error", "args", "kwargs"):
                    continue  # Already shown or handled
                value_str = str(value)
                lines.append(f"           {DIM}{key}:{RESET} {value_str}")

        return lines

    def _format_event_compact(self, event: Any) -> list[str]:
        """Format event in compact mode."""
        lines = []
        time_str = event.timestamp.strftime("%H:%M:%S") if event.timestamp else "--:--:--"
        event_type = format_event_type(event.type.value)

        # Main event line
        lines.append(f"  {DIM}{time_str}{RESET} {event_type}")

        # Show step call signature for step events
        if event.data and "step_name" in event.data:
            step_call = self._format_step_call(event.data)
            lines.append(f"           {Colors.CYAN}{step_call}{RESET}")

        return lines

    def _get_terminal_height(self) -> int:
        """Get terminal height."""
        try:
            import shutil

            return shutil.get_terminal_size().lines
        except Exception:
            return 24  # Default

    def _render(self) -> None:
        """Render current state."""
        with self._lock:
            # Clear previous output
            if self.lines_printed > 0:
                for _ in range(self.lines_printed):
                    move_cursor_up(1)
                    clear_line()

            lines = []

            # Spinner line with status
            frame = SPINNER_FRAMES[self.frame_index]
            status_color = (
                Colors.BLUE
                if self.status == RunStatus.RUNNING
                else (
                    Colors.GREEN
                    if self.status == RunStatus.COMPLETED
                    else (Colors.RED if self.status == RunStatus.FAILED else Colors.YELLOW)
                )
            )
            elapsed_str = f"{self.elapsed:.1f}s"
            event_count = len(self.events)
            mode_indicator = f" {Colors.PRIMARY}[DETAIL]{RESET}" if self.detail_mode else ""
            lines.append(
                f"{status_color}{frame}{RESET} {self.message} ({elapsed_str}) {DIM}[{event_count} events]{RESET}{mode_indicator}"
            )
            lines.append("")

            # Events section - show ALL events
            if self.events:
                lines.append(f"{DIM}Events:{RESET}")

                # Calculate available lines for events
                terminal_height = self._get_terminal_height()
                header_lines = 4  # spinner + blank + "Events:" + footer
                max_event_lines = max(terminal_height - header_lines - 2, 10)

                # Format all events
                all_event_lines = []
                for event in self.events:
                    if self.detail_mode:
                        all_event_lines.extend(self._format_event_detail(event))
                    else:
                        all_event_lines.extend(self._format_event_compact(event))

                # If too many lines, show the most recent ones
                if len(all_event_lines) > max_event_lines:
                    # Show indicator that there are more events
                    hidden_count = len(all_event_lines) - max_event_lines + 1
                    lines.append(f"  {DIM}... ({hidden_count} earlier lines){RESET}")
                    all_event_lines = all_event_lines[-max_event_lines + 1 :]

                lines.extend(all_event_lines)
                lines.append("")

            # Footer with keyboard hints
            lines.append(f"{DIM}Ctrl+O: toggle details | Ctrl+C: stop watching{RESET}")

            # Print all lines
            for line in lines:
                print(line)
            self.lines_printed = len(lines)

            # Advance spinner
            self.frame_index = (self.frame_index + 1) % len(SPINNER_FRAMES)

    def _spin(self) -> None:
        """Background thread for spinner animation."""
        while self.running:
            self._check_keyboard()
            self._render()
            time.sleep(0.1)

    def start(self) -> None:
        """Start the spinner."""
        hide_cursor()
        self.running = True
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop the spinner."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)

        # Restore terminal settings
        self._restore_terminal()

        show_cursor()
        # Final render
        self._render()

    def update(
        self,
        events: list[Any] | None = None,
        status: RunStatus | None = None,
        elapsed: float | None = None,
    ) -> None:
        """Update spinner state."""
        with self._lock:
            if events is not None:
                self.events = events
            if status is not None:
                self.status = status
            if elapsed is not None:
                self.elapsed = elapsed


async def _watch_workflow(
    run_id: str,
    workflow_name: str,
    storage: Any,
    poll_interval: float = 0.5,
    max_wait_for_start: float = 30.0,
    debug: bool = False,
) -> RunStatus:
    """
    Watch a workflow execution with ANSI spinner display.

    Args:
        run_id: Workflow run ID
        workflow_name: Name of the workflow
        storage: Storage backend
        poll_interval: Seconds between polls
        max_wait_for_start: Max seconds to wait for run to be created
        debug: Start in detail mode (show args, results, errors)

    Returns:
        Final workflow status
    """
    start_time = datetime.now()
    seen_event_ids: set[str] = set()
    all_events: list[Any] = []

    terminal_statuses = {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }

    # Wait for the run to be created (with Celery, the worker creates it)
    run = None
    wait_start = datetime.now()
    while run is None:
        run = await pyworkflow.get_workflow_run(run_id, storage=storage)
        if run is None:
            elapsed = (datetime.now() - wait_start).total_seconds()
            if elapsed > max_wait_for_start:
                print_error("Timeout waiting for workflow run to be created")
                print_info("Make sure Celery workers are running: pyworkflow worker run")
                return RunStatus.FAILED
            # Show waiting message
            print(f"{DIM}Waiting for worker to start workflow... ({elapsed:.0f}s){RESET}", end="\r")
            await asyncio.sleep(poll_interval)

    # Clear waiting line
    clear_line()

    # Create spinner display
    spinner = SpinnerDisplay(message=f"Running workflow: {workflow_name}", detail_mode=debug)
    spinner.start()

    try:
        while True:
            try:
                # Fetch current status
                run = await pyworkflow.get_workflow_run(run_id, storage=storage)
                if not run:
                    spinner.stop()
                    print_error(f"Workflow run '{run_id}' not found")
                    return RunStatus.FAILED

                status = run.status

                # Fetch events
                events = await pyworkflow.get_workflow_events(run_id, storage=storage)

                # Track new events
                for event in events:
                    if event.event_id not in seen_event_ids:
                        seen_event_ids.add(event.event_id)
                        all_events.append(event)

                # Sort events by sequence
                all_events.sort(key=lambda e: e.sequence or 0)

                # Calculate elapsed time
                elapsed = (datetime.now() - start_time).total_seconds()

                # Update spinner
                spinner.update(events=all_events, status=status, elapsed=elapsed)

                # Check if workflow is done
                if status in terminal_statuses:
                    await asyncio.sleep(0.3)  # Brief pause for final update
                    spinner.stop()
                    return status

                # Wait before next poll
                await asyncio.sleep(poll_interval)

            except KeyboardInterrupt:
                spinner.stop()
                print(f"\n{DIM}Watch interrupted{RESET}")
                return RunStatus.RUNNING

    except Exception as e:
        spinner.stop()
        print(f"\n{Colors.RED}Error watching workflow: {e}{RESET}")
        return RunStatus.FAILED


@click.group(name="workflows")
def workflows() -> None:
    """Manage workflows (list, info, run)."""
    pass


@workflows.command(name="list")
@click.pass_context
def list_workflows_cmd(ctx: click.Context) -> None:
    """
    List all registered workflows.

    Examples:

        # List workflows from a specific module
        pyworkflow --module myapp.workflows workflows list

        # List workflows with JSON output
        pyworkflow --module myapp.workflows --output json workflows list
    """
    # Get context data
    module = ctx.obj["module"]
    config = ctx.obj["config"]
    output = ctx.obj["output"]

    # Discover workflows
    discover_workflows(module, config)

    # Get registered workflows
    workflows_dict = pyworkflow.list_workflows()

    if not workflows_dict:
        print_info("No workflows registered")
        return

    # Format output
    if output == "json":
        data = [
            {
                "name": name,
                "max_duration": meta.max_duration or "None",
                "tags": meta.tags or [],
            }
            for name, meta in workflows_dict.items()
        ]
        format_json(data)

    elif output == "plain":
        names = list(workflows_dict.keys())
        format_plain(names)

    else:  # table (now displays as list)
        data = [
            {
                "Name": name,
                "Max Duration": meta.max_duration or "-",
                "Tags": ", ".join(meta.tags) if meta.tags else "-",
            }
            for name, meta in workflows_dict.items()
        ]
        format_table(data, ["Name", "Max Duration", "Tags"], title="Registered Workflows")


@workflows.command(name="info")
@click.argument("workflow_name")
@click.pass_context
def workflow_info(ctx: click.Context, workflow_name: str) -> None:
    """
    Show detailed information about a workflow.

    Args:
        WORKFLOW_NAME: Name of the workflow to inspect

    Examples:

        pyworkflow --module myapp.workflows workflows info my_workflow
    """
    # Get context data
    module = ctx.obj["module"]
    config = ctx.obj["config"]
    output = ctx.obj["output"]

    # Discover workflows
    discover_workflows(module, config)

    # Get workflow metadata
    workflow_meta = pyworkflow.get_workflow(workflow_name)

    if not workflow_meta:
        print_error(f"Workflow '{workflow_name}' not found")
        raise click.Abort()

    # Format output
    if output == "json":
        data = {
            "name": workflow_meta.name,
            "max_duration": workflow_meta.max_duration,
            "tags": workflow_meta.tags or [],
            "function": {
                "name": workflow_meta.original_func.__name__,
                "module": workflow_meta.original_func.__module__,
                "doc": workflow_meta.original_func.__doc__,
            },
        }
        format_json(data)

    else:  # table or plain (use key-value format)
        data = {
            "Name": workflow_meta.name,
            "Max Duration": workflow_meta.max_duration or "None",
            "Function": workflow_meta.original_func.__name__,
            "Module": workflow_meta.original_func.__module__,
            "Tags": ", ".join(workflow_meta.tags) if workflow_meta.tags else "-",
        }

        if workflow_meta.original_func.__doc__:
            data["Description"] = workflow_meta.original_func.__doc__.strip()

        format_key_value(data, title=f"Workflow: {workflow_name}")


@workflows.command(name="run")
@click.argument("workflow_name", required=False)
@click.option(
    "--arg",
    multiple=True,
    help="Workflow argument in key=value format (can be repeated)",
)
@click.option(
    "--args-json",
    help="Workflow arguments as JSON string",
)
@click.option(
    "--durable/--no-durable",
    default=True,
    help="Run workflow in durable mode (default: durable)",
)
@click.option(
    "--idempotency-key",
    help="Idempotency key for workflow execution",
)
@click.option(
    "--no-wait",
    is_flag=True,
    default=False,
    help="Don't wait for workflow completion (just start and exit)",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Show detailed event output (args, results, errors)",
)
@click.pass_context
@async_command
async def run_workflow(
    ctx: click.Context,
    workflow_name: str | None,
    arg: tuple,
    args_json: str | None,
    durable: bool,
    idempotency_key: str | None,
    no_wait: bool,
    debug: bool,
) -> None:
    """
    Execute a workflow and watch its progress.

    By default, waits for the workflow to complete, showing real-time events.
    Use --no-wait to start the workflow and exit immediately.

    When run without arguments, displays an interactive menu to select a workflow
    and prompts for any required arguments.

    Args:
        WORKFLOW_NAME: Name of the workflow to run (optional, will prompt if not provided)

    Examples:

        # Interactive mode - select workflow and enter arguments
        pyworkflow --module myapp.workflows workflows run

        # Run workflow with arguments
        pyworkflow --module myapp.workflows workflows run my_workflow \\
            --arg name=John --arg age=30

        # Run workflow with JSON arguments
        pyworkflow --module myapp.workflows workflows run my_workflow \\
            --args-json '{"name": "John", "age": 30}'

        # Run transient workflow
        pyworkflow --module myapp.workflows workflows run my_workflow \\
            --no-durable

        # Run with idempotency key
        pyworkflow --module myapp.workflows workflows run my_workflow \\
            --idempotency-key unique-operation-id
    """
    # Get context data
    module = ctx.obj["module"]
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    runtime_name = ctx.obj.get("runtime", "celery")
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Discover workflows
    discover_workflows(module, config)

    # Get registered workflows
    workflows_dict = pyworkflow.list_workflows()

    # Interactive mode: select workflow if not provided
    if not workflow_name:
        if not workflows_dict:
            print_error("No workflows registered")
            raise click.Abort()

        # Show breadcrumb for step 1
        print_breadcrumb(["workflow", "arguments"], 0)

        workflow_name = await _select_workflow_async(workflows_dict)
        if not workflow_name:
            raise click.Abort()

    # Get workflow metadata
    workflow_meta = pyworkflow.get_workflow(workflow_name)

    if not workflow_meta:
        print_error(f"Workflow '{workflow_name}' not found")
        raise click.Abort()

    # Parse arguments
    kwargs = {}

    # Parse --arg flags
    for arg_pair in arg:
        if "=" not in arg_pair:
            print_error(f"Invalid argument format: {arg_pair}. Expected key=value")
            raise click.Abort()

        key, value = arg_pair.split("=", 1)

        # Try to parse as JSON, fall back to string
        try:
            kwargs[key] = json.loads(value)
        except json.JSONDecodeError:
            kwargs[key] = value

    # Parse --args-json
    if args_json:
        try:
            json_args = json.loads(args_json)
            if not isinstance(json_args, dict):
                print_error("--args-json must be a JSON object")
                raise click.Abort()
            kwargs.update(json_args)
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON in --args-json: {e}")
            raise click.Abort()

    # Interactive mode: prompt for arguments if none provided
    if not kwargs and not arg and not args_json:
        params = _get_workflow_parameters(workflow_meta.original_func)
        if params:
            # Show breadcrumb for step 2
            print_breadcrumb(["workflow", "arguments"], 1)

            prompted_kwargs = await _prompt_for_arguments_async(params)
            kwargs.update(prompted_kwargs)
            print()  # Add spacing after prompts

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Execute workflow
    print_info(f"Starting workflow: {workflow_name}")
    print_info(f"Runtime: {runtime_name}")
    if kwargs:
        print_info(f"Arguments: {json.dumps(kwargs, indent=2)}")

    # Celery runtime requires durable mode
    if runtime_name == "celery" and not durable:
        print_error("Celery runtime requires durable mode. Use --durable or --runtime local")
        raise click.Abort()

    try:
        run_id = await pyworkflow.start(
            workflow_meta.func,
            **kwargs,
            runtime=runtime_name,
            durable=durable,
            storage=storage,
            idempotency_key=idempotency_key,
        )

        # JSON output mode - just output and exit
        if output == "json":
            format_json({"run_id": run_id, "workflow_name": workflow_name, "runtime": runtime_name})
            return

        # No-wait mode - start and exit immediately
        if no_wait:
            print_success("Workflow started successfully")
            print_info(f"Run ID: {run_id}")
            print_info(f"Runtime: {runtime_name}")

            if durable:
                print_info(f"\nCheck status with: pyworkflow runs status {run_id}")
                print_info(f"View logs with: pyworkflow runs logs {run_id}")

            if runtime_name == "celery":
                print_info("\nNote: Workflow dispatched to Celery workers.")
                print_info("Ensure workers are running: pyworkflow worker run")
            return

        # Watch mode (default) - poll and display events until completion
        print(f"{DIM}Started workflow run: {run_id}{RESET}")
        print(f"{DIM}Watching for events... (Ctrl+C to stop watching){RESET}\n")

        # Wait a moment for initial events to be recorded
        await asyncio.sleep(0.5)

        # Watch the workflow
        final_status = await _watch_workflow(
            run_id=run_id,
            workflow_name=workflow_name,
            storage=storage,
            poll_interval=0.5,
            debug=debug,
        )

        # Print final summary
        print()
        if final_status == RunStatus.COMPLETED:
            print_success("Workflow completed successfully")
            # Fetch and show result
            run = await pyworkflow.get_workflow_run(run_id, storage=storage)
            if run and run.result:
                try:
                    result = json.loads(run.result)
                    print(f"{DIM}Result:{RESET} {json.dumps(result, indent=2)}")
                except json.JSONDecodeError:
                    print(f"{DIM}Result:{RESET} {run.result}")
        elif final_status == RunStatus.FAILED:
            print_error("Workflow failed")
            run = await pyworkflow.get_workflow_run(run_id, storage=storage)
            if run and run.error:
                print(f"{Colors.RED}Error:{RESET} {run.error}")
            raise click.Abort()
        elif final_status == RunStatus.CANCELLED:
            print_warning("Workflow was cancelled")
        else:
            # Still running (user interrupted watch)
            print_info(
                f"Workflow still running. Check status with: pyworkflow runs status {run_id}"
            )

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Failed to start workflow: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()
