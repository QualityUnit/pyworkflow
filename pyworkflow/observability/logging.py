"""
Loguru logging configuration for PyWorkflow.

Provides structured logging with context-aware formatting for workflows, steps,
and events. Integrates with loguru for powerful logging capabilities.
"""

import sys
from pathlib import Path
from typing import Any

from loguru import logger


def configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_logs: bool = False,
    show_context: bool = True,
) -> None:
    """
    Configure PyWorkflow logging with loguru.

    This sets up structured logging with workflow context (run_id, step_id, etc.)
    and flexible output formats.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for log output
        json_logs: If True, output logs in JSON format (useful for production)
        show_context: If True, include workflow context in log messages

    Examples:
        # Basic configuration (console output only)
        configure_logging()

        # Debug mode with file output
        configure_logging(level="DEBUG", log_file="workflow.log")

        # Production mode with JSON logs
        configure_logging(
            level="INFO",
            log_file="production.log",
            json_logs=True
        )

        # Minimal logs without context
        configure_logging(level="WARNING", show_context=False)
    """
    # Remove default logger
    logger.remove()

    # Console format
    if json_logs:
        # JSON format for structured logging
        console_format = _get_json_format()
    else:
        # Human-readable format
        if show_context:
            # Include extra context when available (run_id, step_id, etc.)
            console_format = (
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            )
        else:
            console_format = (
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            )

    # Add console handler with filter to inject context
    def format_with_context(record: dict[str, Any]) -> bool:
        """Add context fields to the format string dynamically."""
        extra_str = ""
        if show_context and record["extra"]:
            # Build context string from extra fields
            context_parts = []
            if "run_id" in record["extra"]:
                context_parts.append(f"run_id={record['extra']['run_id']}")
            if "step_id" in record["extra"]:
                context_parts.append(f"step_id={record['extra']['step_id']}")
            if "workflow_name" in record["extra"]:
                context_parts.append(f"workflow={record['extra']['workflow_name']}")
            if context_parts:
                extra_str = " | " + " ".join(context_parts)
        record["extra"]["_context"] = extra_str
        return True

    logger.add(
        sys.stderr,
        format=console_format + "{extra[_context]}",
        level=level,
        colorize=not json_logs,
        serialize=json_logs,
        filter=format_with_context,  # type: ignore[arg-type]
    )

    # Add file handler if requested
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        if json_logs:
            # JSON format for file
            logger.add(
                log_file,
                format=_get_json_format(),
                level=level,
                rotation="100 MB",
                retention="30 days",
                compression="gz",
                serialize=True,
            )
        else:
            # Human-readable format for file
            logger.add(
                log_file,
                format=(
                    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                    "{level: <8} | "
                    "{name}:{function}:{line} | "
                    "{message} | "
                    "{extra}"
                ),
                level=level,
                rotation="100 MB",
                retention="30 days",
                compression="gz",
            )

    logger.info(f"PyWorkflow logging configured at level {level}")


def _get_json_format() -> str:
    """
    Get JSON log format string.

    Returns:
        Format string for JSON structured logging
    """
    return (
        '{{"timestamp":"{time:YYYY-MM-DD HH:mm:ss.SSS}",'
        '"level":"{level}",'
        '"logger":"{name}",'
        '"function":"{function}",'
        '"line":{line},'
        '"message":"{message}",'
        '"extra":{extra}}}'
    )


def get_logger(name: str | None = None) -> Any:
    """
    Get a logger instance.

    This is a convenience function that returns the configured loguru logger
    with optional context binding.

    Args:
        name: Optional logger name (for filtering)

    Returns:
        Configured logger instance

    Examples:
        # Get logger for a module
        log = get_logger(__name__)
        log.info("Processing workflow")

        # Use with context
        log = get_logger().bind(run_id="run_123")
        log.info("Step started")
    """
    if name:
        return logger.bind(module=name)
    return logger


def bind_workflow_context(run_id: str, workflow_name: str) -> Any:
    """
    Bind workflow context to logger.

    This adds run_id and workflow_name to all subsequent log messages.

    Args:
        run_id: Workflow run identifier
        workflow_name: Workflow name

    Returns:
        Logger with bound context

    Example:
        log = bind_workflow_context("run_123", "process_order")
        log.info("Workflow started")
        # Output includes run_id and workflow_name
    """
    return logger.bind(run_id=run_id, workflow_name=workflow_name)


def bind_step_context(run_id: str, step_id: str, step_name: str) -> Any:
    """
    Bind step context to logger.

    This adds run_id, step_id, and step_name to all subsequent log messages.

    Args:
        run_id: Workflow run identifier
        step_id: Step identifier
        step_name: Step name

    Returns:
        Logger with bound context

    Example:
        log = bind_step_context("run_123", "step_abc", "validate_order")
        log.info("Step executing")
        # Output includes run_id, step_id, and step_name
    """
    return logger.bind(run_id=run_id, step_id=step_id, step_name=step_name)


# Default configuration on import
# Users can override by calling configure_logging()
try:
    # Only configure if logger doesn't have handlers
    if len(logger._core.handlers) == 0:  # type: ignore[attr-defined]
        configure_logging(level="INFO", show_context=False)
except Exception:
    # If configuration fails, just use default loguru
    pass
