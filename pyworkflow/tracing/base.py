"""
Abstract base class for tracing providers.

All provider implementations (Langfuse, etc.) must inherit from this class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


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
        parent_span_id: Optional[str] = None,
        trace_name: Optional[str] = None,
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
        metadata: Optional[dict] = None,
        usage_details: Optional[dict] = None,
        cost_details: Optional[dict] = None,
        model: Optional[str] = None,
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
        input: Any = None,
        output: Any = None,
        metadata: Optional[dict] = None,
        name: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        trace_params: Optional[dict] = None,
    ) -> None:
        """Update trace-level attributes (called after shutdown)."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Flush pending data and shut down."""
        pass
