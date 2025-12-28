"""
OpenTelemetry tracing integration for PyWorkflow.

Provides optional distributed tracing for workflows and steps.
Tracing is disabled by default and must be explicitly enabled via configure().

This module gracefully handles the case where OpenTelemetry is not installed,
allowing tracing to be an optional feature.

Example:
    >>> import pyworkflow
    >>> pyworkflow.configure(
    ...     enable_tracing=True,
    ...     tracing_endpoint="http://localhost:4317",  # OTLP endpoint
    ... )
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Generator

from loguru import logger

# Global state for tracing configuration
_tracing_enabled: bool = False
_tracer: Any = None
_current_span: ContextVar[Any] = ContextVar("current_span", default=None)


@dataclass
class TracingConfig:
    """Configuration for OpenTelemetry tracing.

    Attributes:
        enabled: Whether tracing is enabled.
        service_name: Service name for traces.
        endpoint: OTLP/Jaeger endpoint URL.
        exporter: Exporter type ("otlp", "jaeger", "console").
        sample_rate: Sampling rate (0.0 to 1.0).
        propagate_context: Whether to propagate trace context.
    """

    enabled: bool = False
    service_name: str = "pyworkflow"
    endpoint: str | None = None
    exporter: str = "otlp"  # "otlp", "jaeger", "console"
    sample_rate: float = 1.0
    propagate_context: bool = True


def configure_tracing(config: TracingConfig) -> None:
    """Configure and initialize OpenTelemetry tracing.

    This function configures the OpenTelemetry tracer with the specified
    settings. If OpenTelemetry packages are not installed, tracing will
    be disabled and a warning will be logged.

    Args:
        config: TracingConfig instance with tracing settings.

    Note:
        Install tracing dependencies with: pip install pyworkflow[tracing]
    """
    global _tracing_enabled, _tracer

    if not config.enabled:
        _tracing_enabled = False
        _tracer = None
        logger.debug("Tracing is disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        # Create resource
        resource = Resource.create(
            {
                "service.name": config.service_name,
                "service.version": "0.1.0",
            }
        )

        # Create sampler
        sampler = TraceIdRatioBased(config.sample_rate)

        # Create and set tracer provider
        provider = TracerProvider(resource=resource, sampler=sampler)
        trace.set_tracer_provider(provider)

        # Configure exporter if endpoint is provided
        if config.endpoint:
            _configure_exporter(provider, config)

        # Get tracer
        _tracer = trace.get_tracer("pyworkflow", "0.1.0")
        _tracing_enabled = True

        logger.info(
            f"Tracing configured: service={config.service_name}, "
            f"endpoint={config.endpoint}, sample_rate={config.sample_rate}"
        )

    except ImportError as e:
        logger.warning(
            f"OpenTelemetry not installed, tracing disabled: {e}. "
            "Install with: pip install pyworkflow[tracing]"
        )
        _tracing_enabled = False
        _tracer = None


def _configure_exporter(provider: Any, config: TracingConfig) -> None:
    """Configure the trace exporter based on configuration.

    Args:
        provider: TracerProvider instance.
        config: TracingConfig instance.
    """
    if config.exporter == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter = OTLPSpanExporter(endpoint=config.endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.debug(f"OTLP exporter configured for {config.endpoint}")
        except ImportError:
            logger.warning(
                "OTLP exporter not installed: pip install opentelemetry-exporter-otlp"
            )

    elif config.exporter == "jaeger":
        try:
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            # Parse endpoint to extract host
            host = config.endpoint.split("://")[-1].split(":")[0] if config.endpoint else "localhost"
            exporter = JaegerExporter(agent_host_name=host)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.debug(f"Jaeger exporter configured for {host}")
        except ImportError:
            logger.warning(
                "Jaeger exporter not installed: pip install opentelemetry-exporter-jaeger"
            )

    elif config.exporter == "console":
        try:
            from opentelemetry.sdk.trace.export import (
                ConsoleSpanExporter,
                SimpleSpanProcessor,
            )

            exporter = ConsoleSpanExporter()
            provider.add_span_processor(SimpleSpanProcessor(exporter))
            logger.debug("Console exporter configured")
        except ImportError:
            logger.warning("Console exporter not available")


def is_tracing_enabled() -> bool:
    """Check if tracing is currently enabled.

    Returns:
        True if tracing is enabled and configured, False otherwise.
    """
    return _tracing_enabled


@contextmanager
def trace_workflow(
    run_id: str, workflow_name: str, **attributes: Any
) -> Generator[Any, None, None]:
    """Context manager to create a span for a workflow execution.

    Creates an OpenTelemetry span that encompasses the entire workflow
    execution. If tracing is disabled, yields None without any overhead.

    Args:
        run_id: Workflow run ID.
        workflow_name: Workflow name.
        **attributes: Additional span attributes.

    Yields:
        Span object if tracing is enabled, None otherwise.

    Example:
        with trace_workflow("run_123", "process_order", durable=True):
            # Workflow execution code
            pass
    """
    if not _tracing_enabled or _tracer is None:
        yield None
        return

    try:
        from opentelemetry import trace
        from opentelemetry.trace import Status, StatusCode

        with _tracer.start_as_current_span(
            f"workflow:{workflow_name}",
            kind=trace.SpanKind.INTERNAL,
        ) as span:
            span.set_attribute("pyworkflow.run_id", run_id)
            span.set_attribute("pyworkflow.workflow_name", workflow_name)
            span.set_attribute("pyworkflow.type", "workflow")

            for key, value in attributes.items():
                span.set_attribute(f"pyworkflow.{key}", str(value))

            # Store in context var for child spans
            token = _current_span.set(span)

            try:
                yield span
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
            finally:
                _current_span.reset(token)
    except ImportError:
        yield None


@contextmanager
def trace_step(
    step_id: str, step_name: str, attempt: int = 1, **attributes: Any
) -> Generator[Any, None, None]:
    """Context manager to create a span for a step execution.

    Creates an OpenTelemetry span for a step, linked to the parent
    workflow span if one exists. If tracing is disabled, yields None.

    Args:
        step_id: Step ID.
        step_name: Step name.
        attempt: Current retry attempt number.
        **attributes: Additional span attributes.

    Yields:
        Span object if tracing is enabled, None otherwise.

    Example:
        with trace_step("step_abc", "validate_order", attempt=1):
            # Step execution code
            pass
    """
    if not _tracing_enabled or _tracer is None:
        yield None
        return

    try:
        from opentelemetry import trace
        from opentelemetry.trace import Status, StatusCode

        with _tracer.start_as_current_span(
            f"step:{step_name}",
            kind=trace.SpanKind.INTERNAL,
        ) as span:
            span.set_attribute("pyworkflow.step_id", step_id)
            span.set_attribute("pyworkflow.step_name", step_name)
            span.set_attribute("pyworkflow.attempt", attempt)
            span.set_attribute("pyworkflow.type", "step")

            for key, value in attributes.items():
                span.set_attribute(f"pyworkflow.{key}", str(value))

            try:
                yield span
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                span.set_attribute("pyworkflow.error_type", type(e).__name__)
                raise
    except ImportError:
        yield None


def add_span_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    """Add an event to the current span.

    Events are timestamped points in time within a span that can be
    used to record notable occurrences.

    Args:
        name: Event name.
        attributes: Optional event attributes.

    Example:
        add_span_event("step_started", {"step_name": "validate"})
    """
    if not _tracing_enabled:
        return

    span = _current_span.get()
    if span is not None:
        try:
            span.add_event(name, attributes=attributes or {})
        except Exception:
            pass  # Ignore errors when adding events


def set_span_attribute(key: str, value: Any) -> None:
    """Set an attribute on the current span.

    Args:
        key: Attribute key (will be prefixed with "pyworkflow.").
        value: Attribute value.

    Example:
        set_span_attribute("result_count", 42)
    """
    if not _tracing_enabled:
        return

    span = _current_span.get()
    if span is not None:
        try:
            span.set_attribute(f"pyworkflow.{key}", str(value))
        except Exception:
            pass  # Ignore errors when setting attributes


def get_trace_context() -> dict[str, str] | None:
    """Get current trace context for propagation.

    Returns the trace context headers (traceparent, tracestate) that
    can be used to propagate trace context across service boundaries.

    Returns:
        Dictionary with trace context headers, or None if tracing is disabled.

    Example:
        context = get_trace_context()
        if context:
            headers.update(context)
    """
    if not _tracing_enabled:
        return None

    try:
        from opentelemetry.propagate import inject

        carrier: dict[str, str] = {}
        inject(carrier)
        return carrier if carrier else None
    except ImportError:
        return None


def inject_trace_context(headers: dict[str, str]) -> None:
    """Inject trace context into headers for propagation.

    Modifies the headers dictionary in-place to add trace context.

    Args:
        headers: Dictionary to inject trace context into.

    Example:
        headers = {"Content-Type": "application/json"}
        inject_trace_context(headers)
        # headers now includes traceparent and tracestate
    """
    if not _tracing_enabled:
        return

    try:
        from opentelemetry.propagate import inject

        inject(headers)
    except ImportError:
        pass


def extract_trace_context(headers: dict[str, str]) -> Any:
    """Extract trace context from incoming headers.

    Used to continue a trace that was started in another service.

    Args:
        headers: Dictionary containing trace context headers.

    Returns:
        Context object if extraction successful, None otherwise.

    Example:
        context = extract_trace_context(request.headers)
        with tracer.start_span("operation", context=context):
            pass
    """
    if not _tracing_enabled:
        return None

    try:
        from opentelemetry.propagate import extract

        return extract(headers)
    except ImportError:
        return None
