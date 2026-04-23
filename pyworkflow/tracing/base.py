"""
Abstract base class for tracing providers.

All provider implementations (Langfuse, etc.) must inherit from this class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from pyworkflow.tracing.types import TracingStepResult


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

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def record_step_span(
        self,
        *,
        trace_id: str,
        step_name: str,
        step_id: str,
        is_generator: bool,
        result: Any,
        step_input: dict | None = None,
        trace_name: str | None = None,
    ) -> None:
        """Emit a span for a completed step, including child LLM/tool spans.

        Coerces ``result`` through :meth:`TracingStepResult.model_validate` so
        that subclass-specific fields are discarded and ``llm_calls`` /
        ``tool_calls`` become typed objects. Silent no-op when the result
        cannot be coerced.
        """
        if isinstance(result, BaseModel):
            data = result.model_dump()
        elif isinstance(result, dict):
            data = result
        else:
            return

        try:
            tr = TracingStepResult.model_validate(data)
        except ValidationError:
            return

        span = self.start_span_on_trace(
            trace_id,
            f"{step_name}-{step_id}",
            is_generator=is_generator,
            trace_name=trace_name,
        )
        if not span:
            return

        self.update_span(
            span,
            input=step_input or None,
            output={"text_output": data.get("text_output", "")},
        )

        if tr.llm_calls and is_generator:
            self.update_span(
                span,
                usage_details={
                    "input_tokens": tr.total_input_tokens,
                    "output_tokens": tr.total_output_tokens,
                    "total_tokens": tr.total_tokens,
                },
                model=tr.model,
            )
        elif tr.llm_calls:
            for lc in tr.llm_calls:
                gen = self.start_child_generation(span, "LLM Call")
                if gen:
                    self.update_span(
                        gen,
                        usage_details={
                            "input_tokens": lc.input_tokens,
                            "output_tokens": lc.output_tokens,
                            "total_tokens": lc.total_tokens,
                        },
                        model=tr.model,
                    )
                    self.end_span(gen)

        for tc in tr.tool_calls:
            ts = self.start_child_span(span, tc.name or "tool")
            if ts:
                self.update_span(ts, input=tc.input, output=tc.output)
                self.end_span(ts)

        self.end_span(span)
