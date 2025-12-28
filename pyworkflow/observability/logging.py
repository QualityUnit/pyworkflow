"""
Loguru logging configuration for PyWorkflow.

Provides structured logging with context-aware formatting for workflows, steps,
and events. Integrates with loguru for powerful logging capabilities.

Features:
- Environment variable configuration for production deployments
- Standard JSON schema compatible with ELK/Loki/Datadog
- Context managers for scoped logging
- Automatic context binding for workflows and steps
"""

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generator

from loguru import logger


@dataclass
class LogContext:
    """Structured context for workflow logging.

    Provides a consistent way to track execution context across
    workflows and steps for debugging and observability.
    """

    run_id: str | None = None
    workflow_name: str | None = None
    step_id: str | None = None
    step_name: str | None = None
    attempt: int | None = None


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

    if json_logs:
        # JSON format using custom serializer for ELK/Loki/Datadog compatibility
        logger.add(
            sys.stderr,
            format="{message}",
            level=level,
            colorize=False,
            serialize=False,
            filter=_create_json_filter(show_context),
        )
    else:
        # Human-readable format
        if show_context:
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
            colorize=True,
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
                format="{message}",
                level=level,
                rotation="100 MB",
                retention="30 days",
                compression="gz",
                serialize=False,
                filter=_create_json_filter(show_context),
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


def _create_json_filter(show_context: bool) -> Any:
    """Create a filter function that formats logs as JSON.

    Args:
        show_context: Whether to include context in logs.

    Returns:
        Filter function for loguru.
    """

    def json_filter(record: dict[str, Any]) -> bool:
        """Format log record as JSON and replace message."""
        log_entry = _format_for_json(record, show_context)
        record["message"] = log_entry
        return True

    return json_filter


def _format_for_json(record: dict[str, Any], show_context: bool = True) -> str:
    """Format log record as JSON compatible with log aggregators.

    Produces a standard JSON schema that works with ELK, Loki, Datadog,
    and other log aggregation systems.

    Args:
        record: Loguru log record.
        show_context: Whether to include context fields.

    Returns:
        JSON string representation of the log.
    """
    # Extract context fields
    context_keys = {"run_id", "workflow_name", "step_id", "step_name", "attempt"}

    context = {}
    extra = {}

    for key, value in record["extra"].items():
        if key.startswith("_"):
            continue  # Skip internal fields
        if key in context_keys:
            context[key] = value
        else:
            extra[key] = _safe_serialize(value)

    # Build JSON object
    log_obj: dict[str, Any] = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "logger": record["name"],
        "function": record["function"],
        "line": record["line"],
    }

    if show_context and context:
        log_obj["context"] = context

    if extra:
        log_obj["extra"] = extra

    # Add exception info if present
    if record["exception"] is not None:
        log_obj["exception"] = {
            "type": record["exception"].type.__name__ if record["exception"].type else None,
            "value": str(record["exception"].value) if record["exception"].value else None,
            "traceback": record["exception"].traceback is not None,
        }

    return json.dumps(log_obj, default=str)


def _safe_serialize(value: Any) -> Any:
    """Safely serialize a value for JSON output.

    Args:
        value: Value to serialize.

    Returns:
        JSON-serializable value.
    """
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_serialize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_serialize(v) for k, v in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def configure_logging_from_env() -> None:
    """Configure logging from environment variables.

    Environment variables:
        PYWORKFLOW_LOG_LEVEL: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        PYWORKFLOW_LOG_FORMAT: Log format ("json" or "console")
        PYWORKFLOW_LOG_FILE: Optional file path for log output
        PYWORKFLOW_LOG_CONTEXT: Whether to show context ("true" or "false")

    Examples:
        # In shell before running application
        export PYWORKFLOW_LOG_LEVEL=INFO
        export PYWORKFLOW_LOG_FORMAT=json
        export PYWORKFLOW_LOG_FILE=/var/log/pyworkflow.log
    """
    level = os.getenv("PYWORKFLOW_LOG_LEVEL", "INFO").upper()
    format_type = os.getenv("PYWORKFLOW_LOG_FORMAT", "console").lower()
    log_file = os.getenv("PYWORKFLOW_LOG_FILE")
    show_context_str = os.getenv("PYWORKFLOW_LOG_CONTEXT", "true").lower()
    show_context = show_context_str in ("true", "1", "yes")

    configure_logging(
        level=level,
        log_file=log_file,
        json_logs=(format_type == "json"),
        show_context=show_context,
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


@contextmanager
def workflow_logging_context(
    run_id: str, workflow_name: str
) -> Generator[None, None, None]:
    """Context manager to bind workflow context to all logs within scope.

    This ensures all logs within the context include workflow metadata,
    making it easier to trace execution in log aggregators.

    Args:
        run_id: Workflow run identifier.
        workflow_name: Workflow name.

    Yields:
        None

    Example:
        with workflow_logging_context("run_123", "process_order"):
            logger.info("Starting workflow")  # Includes run_id and workflow_name
            # ... workflow execution ...
            logger.info("Workflow complete")  # Also includes context
    """
    with logger.contextualize(run_id=run_id, workflow_name=workflow_name):
        yield


@contextmanager
def step_logging_context(
    run_id: str, step_id: str, step_name: str, attempt: int = 1
) -> Generator[None, None, None]:
    """Context manager to bind step context to all logs within scope.

    This ensures all logs within the context include step metadata,
    making it easier to trace step execution and retries.

    Args:
        run_id: Workflow run identifier.
        step_id: Step identifier.
        step_name: Step name.
        attempt: Current retry attempt number.

    Yields:
        None

    Example:
        with step_logging_context("run_123", "step_abc", "validate_order", attempt=1):
            logger.info("Executing step")  # Includes all step context
            # ... step execution ...
    """
    with logger.contextualize(
        run_id=run_id, step_id=step_id, step_name=step_name, attempt=attempt
    ):
        yield


# Default configuration on import
# Users can override by calling configure_logging() or configure_logging_from_env()
try:
    # Only configure if logger doesn't have handlers
    if len(logger._core.handlers) == 0:  # type: ignore[attr-defined]
        # Check for environment variable to auto-configure
        if os.getenv("PYWORKFLOW_LOG_LEVEL") or os.getenv("PYWORKFLOW_LOG_FORMAT"):
            configure_logging_from_env()
        else:
            configure_logging(level="INFO", show_context=False)
except Exception:
    # If configuration fails, just use default loguru
    pass
