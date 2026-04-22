"""
Abstract base class for tracing providers.

All provider implementations (Langfuse, etc.) must inherit from this class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTracingProvider(ABC):
    """Abstract tracing provider interface for workflow/step observability."""

    # ------------------------------------------------------------------
    # Span lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def start_span_on_trace(
        self,
        trace_id: str,
        name: str,
        is_generator: bool = False,
        parent_span_id: str | None = None,
        trace_name: str | None = None,
    ) -> Any:
        """Start a span attached to a trace. Returns span object or None."""
        pass

    @abstractmethod
    def start_child_span(self, parent_span: Any, name: str) -> Any:
        """Start a child span under a parent span."""
        pass

    @abstractmethod
    def start_child_generation(self, parent_span: Any, name: str) -> Any:
        """Start a generation span under a parent span."""
        pass

    @staticmethod
    @abstractmethod
    def end_span(span: Any) -> None:
        """End a span. No-op if None."""
        pass

    @staticmethod
    @abstractmethod
    def update_span(
        span: Any,
        input: Any = None,
        output: Any = None,
        metadata: dict | None = None,
        usage_details: dict | None = None,
        model: str | None = None,
    ) -> None:
        """Update a span with input/output/metadata/usage."""
        pass

    # ------------------------------------------------------------------
    # Trace lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def update_trace(
        self,
        trace_id: str,
        name: str | None = None,
        input: Any = None,
        output: Any = None,
        trace_params: dict | None = None,
    ) -> None:
        """Update trace-level attributes (called after shutdown)."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Flush pending data and shut down."""
        pass
