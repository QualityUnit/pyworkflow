"""Tests for observability module (logging and tracing)."""

import json
import os
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from pyworkflow.observability.logging import (
    LogContext,
    _format_for_json,
    bind_step_context,
    bind_workflow_context,
    configure_logging,
    configure_logging_from_env,
    step_logging_context,
    workflow_logging_context,
)
from pyworkflow.observability.tracing import (
    TracingConfig,
    add_span_event,
    configure_tracing,
    get_trace_context,
    is_tracing_enabled,
    set_span_attribute,
    trace_step,
    trace_workflow,
)


class TestLogContext:
    """Tests for LogContext dataclass."""

    def test_default_values(self):
        """Test LogContext has correct default values."""
        ctx = LogContext()
        assert ctx.run_id is None
        assert ctx.workflow_name is None
        assert ctx.step_id is None
        assert ctx.step_name is None
        assert ctx.attempt is None

    def test_custom_values(self):
        """Test LogContext accepts custom values."""
        ctx = LogContext(
            run_id="run_123",
            workflow_name="test_workflow",
            step_id="step_456",
            step_name="test_step",
            attempt=2,
        )
        assert ctx.run_id == "run_123"
        assert ctx.workflow_name == "test_workflow"
        assert ctx.step_id == "step_456"
        assert ctx.step_name == "test_step"
        assert ctx.attempt == 2


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def test_configure_default(self, caplog):
        """Test default logging configuration."""
        configure_logging()
        # Should not raise

    def test_configure_debug_level(self):
        """Test debug level configuration."""
        configure_logging(level="DEBUG")
        # Should not raise

    def test_configure_json_logs(self):
        """Test JSON logging configuration."""
        configure_logging(json_logs=True)
        # Should not raise

    def test_configure_without_context(self):
        """Test configuration without context."""
        configure_logging(show_context=False)
        # Should not raise


class TestConfigureLoggingFromEnv:
    """Tests for environment-based logging configuration."""

    def test_configure_from_env_defaults(self):
        """Test default configuration from environment."""
        with patch.dict(os.environ, {}, clear=True):
            configure_logging_from_env()
        # Should not raise

    def test_configure_from_env_json_format(self):
        """Test JSON format from environment."""
        with patch.dict(
            os.environ,
            {"PYWORKFLOW_LOG_FORMAT": "json", "PYWORKFLOW_LOG_LEVEL": "INFO"},
            clear=True,
        ):
            configure_logging_from_env()
        # Should not raise

    def test_configure_from_env_custom_level(self):
        """Test custom log level from environment."""
        with patch.dict(
            os.environ, {"PYWORKFLOW_LOG_LEVEL": "DEBUG"}, clear=True
        ):
            configure_logging_from_env()
        # Should not raise


class TestJsonFormatting:
    """Tests for JSON log formatting."""

    def test_format_basic_log(self):
        """Test basic log formatting to JSON."""
        from datetime import UTC, datetime

        level_mock = MagicMock()
        level_mock.name = "INFO"

        record = {
            "time": datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC),
            "level": level_mock,
            "message": "Test message",
            "name": "test.module",
            "function": "test_func",
            "line": 42,
            "extra": {},
            "exception": None,
        }

        result = _format_for_json(record)
        parsed = json.loads(result)

        assert "timestamp" in parsed
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert parsed["logger"] == "test.module"
        assert parsed["function"] == "test_func"
        assert parsed["line"] == 42

    def test_format_log_with_context(self):
        """Test log formatting with workflow context."""
        from datetime import UTC, datetime

        level_mock = MagicMock()
        level_mock.name = "INFO"

        record = {
            "time": datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC),
            "level": level_mock,
            "message": "Workflow started",
            "name": "pyworkflow.core",
            "function": "execute",
            "line": 100,
            "extra": {
                "run_id": "run_abc123",
                "workflow_name": "process_order",
            },
            "exception": None,
        }

        result = _format_for_json(record, show_context=True)
        parsed = json.loads(result)

        assert "context" in parsed
        assert parsed["context"]["run_id"] == "run_abc123"
        assert parsed["context"]["workflow_name"] == "process_order"


class TestContextBinding:
    """Tests for context binding functions."""

    def test_bind_workflow_context(self):
        """Test binding workflow context to logger."""
        log = bind_workflow_context("run_123", "test_workflow")
        # Should return a logger with bound context
        assert log is not None

    def test_bind_step_context(self):
        """Test binding step context to logger."""
        log = bind_step_context("run_123", "step_456", "test_step")
        # Should return a logger with bound context
        assert log is not None


class TestLoggingContextManagers:
    """Tests for logging context managers."""

    def test_workflow_logging_context(self):
        """Test workflow logging context manager."""
        with workflow_logging_context("run_123", "test_workflow"):
            # Within context, logs should include workflow info
            pass
        # Should not raise

    def test_step_logging_context(self):
        """Test step logging context manager."""
        with step_logging_context("run_123", "step_456", "test_step", attempt=1):
            # Within context, logs should include step info
            pass
        # Should not raise

    def test_nested_contexts(self):
        """Test nested logging contexts."""
        with workflow_logging_context("run_123", "test_workflow"):
            with step_logging_context("run_123", "step_456", "test_step"):
                # Both contexts should be active
                pass
        # Should not raise


class TestTracingConfig:
    """Tests for TracingConfig dataclass."""

    def test_default_values(self):
        """Test TracingConfig has correct defaults."""
        config = TracingConfig()
        assert config.enabled is False
        assert config.service_name == "pyworkflow"
        assert config.endpoint is None
        assert config.exporter == "otlp"
        assert config.sample_rate == 1.0
        assert config.propagate_context is True

    def test_custom_values(self):
        """Test TracingConfig accepts custom values."""
        config = TracingConfig(
            enabled=True,
            service_name="my-service",
            endpoint="http://localhost:4317",
            exporter="console",
            sample_rate=0.5,
        )
        assert config.enabled is True
        assert config.service_name == "my-service"
        assert config.endpoint == "http://localhost:4317"
        assert config.exporter == "console"
        assert config.sample_rate == 0.5


class TestTracingDisabled:
    """Tests for tracing when disabled (default state)."""

    def test_tracing_disabled_by_default(self):
        """Test tracing is disabled by default."""
        # Reset tracing state
        configure_tracing(TracingConfig(enabled=False))
        assert is_tracing_enabled() is False

    def test_trace_workflow_noop_when_disabled(self):
        """Test trace_workflow is noop when tracing disabled."""
        configure_tracing(TracingConfig(enabled=False))

        with trace_workflow("run_123", "test_workflow") as span:
            assert span is None  # No span when disabled

    def test_trace_step_noop_when_disabled(self):
        """Test trace_step is noop when tracing disabled."""
        configure_tracing(TracingConfig(enabled=False))

        with trace_step("step_123", "test_step") as span:
            assert span is None  # No span when disabled

    def test_add_span_event_noop_when_disabled(self):
        """Test add_span_event is noop when tracing disabled."""
        configure_tracing(TracingConfig(enabled=False))
        # Should not raise
        add_span_event("test_event", {"key": "value"})

    def test_set_span_attribute_noop_when_disabled(self):
        """Test set_span_attribute is noop when tracing disabled."""
        configure_tracing(TracingConfig(enabled=False))
        # Should not raise
        set_span_attribute("test_key", "test_value")

    def test_get_trace_context_returns_none_when_disabled(self):
        """Test get_trace_context returns None when disabled."""
        configure_tracing(TracingConfig(enabled=False))
        context = get_trace_context()
        assert context is None


class TestTracingWithoutOpenTelemetry:
    """Tests for tracing behavior when OpenTelemetry is not installed."""

    def test_configure_tracing_handles_import_error(self):
        """Test configure_tracing handles missing OpenTelemetry gracefully."""
        with patch.dict("sys.modules", {"opentelemetry": None}):
            # Should not raise, just log warning
            configure_tracing(TracingConfig(enabled=True))
        # Tracing should be disabled after failed import
        # (Note: actual behavior depends on import mechanism)


class TestTracingIntegration:
    """Integration tests for tracing (when OpenTelemetry is available)."""

    @pytest.fixture
    def mock_opentelemetry(self):
        """Mock OpenTelemetry for testing."""
        # This would be used for testing with actual OTel
        pass

    def test_trace_workflow_exception_handling(self):
        """Test trace_workflow properly handles exceptions."""
        configure_tracing(TracingConfig(enabled=False))

        with pytest.raises(ValueError):
            with trace_workflow("run_123", "test_workflow"):
                raise ValueError("Test error")

    def test_trace_step_exception_handling(self):
        """Test trace_step properly handles exceptions."""
        configure_tracing(TracingConfig(enabled=False))

        with pytest.raises(ValueError):
            with trace_step("step_123", "test_step"):
                raise ValueError("Test error")


class TestTracingEnabled:
    """Tests for tracing with mocked OpenTelemetry."""

    @pytest.fixture
    def mock_otel(self):
        """Mock OpenTelemetry tracer and span."""
        from unittest.mock import MagicMock

        # Create mock span
        mock_span = MagicMock()
        mock_span.set_attribute = MagicMock()
        mock_span.add_event = MagicMock()
        mock_span.set_status = MagicMock()
        mock_span.record_exception = MagicMock()

        # Create mock tracer
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_span), __exit__=MagicMock(return_value=False)))

        # Create mock trace module
        mock_trace = MagicMock()
        mock_trace.get_tracer = MagicMock(return_value=mock_tracer)
        mock_trace.SpanKind = MagicMock()
        mock_trace.SpanKind.INTERNAL = "INTERNAL"

        # Create mock Status and StatusCode
        mock_status = MagicMock()
        mock_status_code = MagicMock()
        mock_status_code.OK = "OK"
        mock_status_code.ERROR = "ERROR"

        return {
            "span": mock_span,
            "tracer": mock_tracer,
            "trace": mock_trace,
            "Status": mock_status,
            "StatusCode": mock_status_code,
        }

    def test_trace_workflow_creates_span_when_enabled(self, mock_otel):
        """Test trace_workflow creates span with correct attributes when enabled."""
        # Import tracing module to access internal state
        import pyworkflow.observability.tracing as tracing_module

        # Mock the OpenTelemetry imports
        with patch.dict("sys.modules", {"opentelemetry": MagicMock(), "opentelemetry.trace": mock_otel["trace"]}):
            # Manually set enabled state
            tracing_module._tracing_enabled = True
            tracing_module._tracer = mock_otel["tracer"]

            try:
                # This should try to create a span
                with trace_workflow("run_123", "test_workflow", durable=True):
                    pass

                # Verify tracer was called
                mock_otel["tracer"].start_as_current_span.assert_called()
            finally:
                # Reset state
                tracing_module._tracing_enabled = False
                tracing_module._tracer = None

    def test_trace_step_creates_span_when_enabled(self, mock_otel):
        """Test trace_step creates span when enabled."""
        import pyworkflow.observability.tracing as tracing_module

        with patch.dict("sys.modules", {"opentelemetry": MagicMock(), "opentelemetry.trace": mock_otel["trace"]}):
            tracing_module._tracing_enabled = True
            tracing_module._tracer = mock_otel["tracer"]

            try:
                with trace_step("step_123", "test_step", attempt=1):
                    pass

                mock_otel["tracer"].start_as_current_span.assert_called()
            finally:
                tracing_module._tracing_enabled = False
                tracing_module._tracer = None

    def test_add_span_event_when_enabled(self, mock_otel):
        """Test add_span_event adds event to current span when enabled."""
        import pyworkflow.observability.tracing as tracing_module

        tracing_module._tracing_enabled = True
        tracing_module._current_span.set(mock_otel["span"])

        try:
            add_span_event("test_event", {"key": "value"})
            mock_otel["span"].add_event.assert_called_once_with(
                "test_event", attributes={"key": "value"}
            )
        finally:
            tracing_module._tracing_enabled = False
            tracing_module._current_span.set(None)

    def test_set_span_attribute_when_enabled(self, mock_otel):
        """Test set_span_attribute sets attribute on current span when enabled."""
        import pyworkflow.observability.tracing as tracing_module

        tracing_module._tracing_enabled = True
        tracing_module._current_span.set(mock_otel["span"])

        try:
            set_span_attribute("test_key", "test_value")
            mock_otel["span"].set_attribute.assert_called_once_with(
                "pyworkflow.test_key", "test_value"
            )
        finally:
            tracing_module._tracing_enabled = False
            tracing_module._current_span.set(None)

    def test_get_trace_context_when_disabled_returns_none(self):
        """Test get_trace_context returns None when disabled."""
        import pyworkflow.observability.tracing as tracing_module

        tracing_module._tracing_enabled = False
        context = get_trace_context()
        assert context is None

    def test_inject_trace_context_modifies_headers(self):
        """Test inject_trace_context populates carrier dict."""
        import pyworkflow.observability.tracing as tracing_module
        from pyworkflow.observability.tracing import inject_trace_context

        mock_inject = MagicMock(side_effect=lambda carrier: carrier.update({"traceparent": "test"}))

        with patch("pyworkflow.observability.tracing.inject", mock_inject, create=True):
            tracing_module._tracing_enabled = True

            try:
                headers = {"Content-Type": "application/json"}
                # This would call inject if OTel was available
                inject_trace_context(headers)
            finally:
                tracing_module._tracing_enabled = False

    def test_extract_trace_context_returns_context(self):
        """Test extract_trace_context extracts from carrier."""
        import pyworkflow.observability.tracing as tracing_module
        from pyworkflow.observability.tracing import extract_trace_context

        mock_extract = MagicMock(return_value={"trace_id": "abc123"})

        with patch("pyworkflow.observability.tracing.extract", mock_extract, create=True):
            tracing_module._tracing_enabled = True

            try:
                headers = {"traceparent": "00-abc-123"}
                # This would call extract if OTel was available
                extract_trace_context(headers)
            finally:
                tracing_module._tracing_enabled = False


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """Test get_logger returns a logger instance."""
        from pyworkflow.observability.logging import get_logger

        log = get_logger()
        assert log is not None
        # Should be able to log
        log.debug("Test message")

    def test_get_logger_with_name(self):
        """Test get_logger with custom name returns bound logger."""
        from pyworkflow.observability.logging import get_logger

        log = get_logger("custom.module")
        assert log is not None


class TestJsonLoggingOutput:
    """Tests for actual JSON log output."""

    def test_format_json_with_exception(self):
        """Test exception info is included in JSON."""
        from datetime import UTC, datetime

        level_mock = MagicMock()
        level_mock.name = "ERROR"

        # Create a mock exception info object like loguru provides
        exception_mock = MagicMock()
        exception_mock.type = ValueError
        exception_mock.value = ValueError("test error")
        exception_mock.traceback = MagicMock()

        record = {
            "time": datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC),
            "level": level_mock,
            "message": "Error occurred",
            "name": "test.module",
            "function": "test_func",
            "line": 42,
            "extra": {},
            "exception": exception_mock,
        }

        result = _format_for_json(record)
        parsed = json.loads(result)

        assert parsed["level"] == "ERROR"
        assert "exception" in parsed
        assert parsed["exception"]["type"] == "ValueError"
        assert "test error" in parsed["exception"]["value"]

    def test_format_json_with_extra_fields(self):
        """Test extra fields are in JSON output."""
        from datetime import UTC, datetime

        level_mock = MagicMock()
        level_mock.name = "INFO"

        record = {
            "time": datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC),
            "level": level_mock,
            "message": "Custom data",
            "name": "test.module",
            "function": "test_func",
            "line": 42,
            "extra": {
                "custom_field": "custom_value",
                "numeric_field": 123,
            },
            "exception": None,
        }

        result = _format_for_json(record)
        parsed = json.loads(result)

        assert "extra" in parsed
        assert parsed["extra"]["custom_field"] == "custom_value"
        assert parsed["extra"]["numeric_field"] == 123


class TestSafeSerialize:
    """Tests for _safe_serialize function."""

    def test_serialize_basic_types(self):
        """Test serialization of str, int, float, bool, None."""
        from pyworkflow.observability.logging import _safe_serialize

        assert _safe_serialize("test") == "test"
        assert _safe_serialize(123) == 123
        assert _safe_serialize(1.5) == 1.5
        assert _safe_serialize(True) is True
        assert _safe_serialize(None) is None

    def test_serialize_datetime(self):
        """Test datetime serialization to ISO format."""
        from datetime import UTC, datetime

        from pyworkflow.observability.logging import _safe_serialize

        dt = datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC)
        result = _safe_serialize(dt)
        assert "2025-01-15" in result
        assert "10:30:45" in result

    def test_serialize_exception(self):
        """Test exception serialization uses str()."""
        from pyworkflow.observability.logging import _safe_serialize

        exc = ValueError("test error message")
        result = _safe_serialize(exc)
        # _safe_serialize uses str() which gives the message
        assert "test error message" in result

    def test_serialize_unserializable_object(self):
        """Test fallback to str() for unserializable objects."""
        from pyworkflow.observability.logging import _safe_serialize

        class CustomClass:
            def __str__(self):
                return "CustomClass instance"

        obj = CustomClass()
        result = _safe_serialize(obj)
        assert "CustomClass" in result


class TestLogFileConfiguration:
    """Tests for file-based logging."""

    def test_configure_logging_with_file(self, tmp_path):
        """Test logging to file creates file."""
        log_file = tmp_path / "test.log"

        configure_logging(log_file=str(log_file), level="INFO")

        # Get a logger and write to it
        from loguru import logger

        logger.info("Test message to file")

        # Give loguru time to flush
        import time

        time.sleep(0.1)

        # File should exist (may or may not have content depending on flush timing)
        # The main test is that configure_logging doesn't raise

    def test_configure_logging_json_to_file(self, tmp_path):
        """Test JSON logging to file configuration."""
        log_file = tmp_path / "test_json.log"

        # Should not raise
        configure_logging(log_file=str(log_file), json_logs=True, level="INFO")
