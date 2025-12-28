"""
Observability and logging for PyWorkflow.

Provides structured logging, metrics, and tracing capabilities for workflows.

Logging:
    - configure_logging(): Configure loguru-based logging
    - configure_logging_from_env(): Configure from environment variables
    - get_logger(): Get a logger instance
    - bind_workflow_context(): Bind workflow context to logger
    - bind_step_context(): Bind step context to logger
    - workflow_logging_context(): Context manager for workflow logging
    - step_logging_context(): Context manager for step logging

Tracing (requires `pip install pyworkflow[tracing]`):
    - TracingConfig: Configuration dataclass for tracing
    - configure_tracing(): Configure OpenTelemetry tracing
    - is_tracing_enabled(): Check if tracing is enabled
    - trace_workflow(): Context manager for workflow spans
    - trace_step(): Context manager for step spans
    - add_span_event(): Add event to current span
    - set_span_attribute(): Set attribute on current span
    - get_trace_context(): Get trace context for propagation
    - inject_trace_context(): Inject trace context into headers
"""

from pyworkflow.observability.logging import (
    LogContext,
    bind_step_context,
    bind_workflow_context,
    configure_logging,
    configure_logging_from_env,
    get_logger,
    step_logging_context,
    workflow_logging_context,
)
from pyworkflow.observability.tracing import (
    TracingConfig,
    add_span_event,
    configure_tracing,
    extract_trace_context,
    get_trace_context,
    inject_trace_context,
    is_tracing_enabled,
    set_span_attribute,
    trace_step,
    trace_workflow,
)

__all__ = [
    # Logging
    "configure_logging",
    "configure_logging_from_env",
    "get_logger",
    "bind_workflow_context",
    "bind_step_context",
    "workflow_logging_context",
    "step_logging_context",
    "LogContext",
    # Tracing
    "TracingConfig",
    "configure_tracing",
    "is_tracing_enabled",
    "trace_workflow",
    "trace_step",
    "add_span_event",
    "set_span_attribute",
    "get_trace_context",
    "inject_trace_context",
    "extract_trace_context",
]
