"""
Langfuse tracing provider implementation.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from pyworkflow.tracing.base import BaseTracingProvider


class LangfuseTracingProvider(BaseTracingProvider):
    """Langfuse implementation of the tracing provider."""

    def __init__(self, public_key: str, secret_key: str, host: str):
        self._public_key = public_key
        self._secret_key = secret_key
        self._host = host
        try:
            from langfuse import Langfuse
            from opentelemetry.sdk.trace import TracerProvider

            self._langfuse = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                tracer_provider=TracerProvider(),
            )
        except Exception as e:
            logger.debug(f"Failed to initialize Langfuse client: {e}")
            self._langfuse = None

    # ------------------------------------------------------------------
    # Span lifecycle
    # ------------------------------------------------------------------

    def start_span_on_trace(
        self,
        trace_id: str,
        name: str,
        is_generator: bool = False,
        parent_span_id: str | None = None,
        trace_name: str | None = None,
    ) -> Any:
        if not self._langfuse:
            return None
        try:
            from langfuse import propagate_attributes

            as_type = "generation" if is_generator else "span"
            trace_context = {"trace_id": trace_id}
            if parent_span_id:
                trace_context["parent_span_id"] = parent_span_id
            effective_trace_name = trace_name or "workflow"
            with propagate_attributes(trace_name=effective_trace_name):
                span = self._langfuse.start_observation(
                    name=name,
                    as_type=as_type,
                    trace_context=trace_context,
                )
            return span
        except Exception as e:
            logger.debug(f"Failed to start span {name}: {e}")
            return None

    def start_child_span(self, parent_span: Any, name: str) -> Any:
        if not self._langfuse or not parent_span:
            return None
        try:
            from opentelemetry.trace import use_span as otel_use_span

            if hasattr(parent_span, "_otel_span"):
                with otel_use_span(parent_span._otel_span, end_on_exit=False):
                    return self._langfuse.start_observation(name=name, as_type="span")
            return self._langfuse.start_observation(name=name, as_type="span")
        except Exception as e:
            logger.debug(f"Failed to start child span: {e}")
            return None

    def start_child_generation(self, parent_span: Any, name: str) -> Any:
        if not self._langfuse or not parent_span:
            return None
        try:
            from opentelemetry.trace import use_span as otel_use_span

            if hasattr(parent_span, "_otel_span"):
                with otel_use_span(parent_span._otel_span, end_on_exit=False):
                    return self._langfuse.start_observation(name=name, as_type="generation")
            return self._langfuse.start_observation(name=name, as_type="generation")
        except Exception as e:
            logger.debug(f"Failed to start child generation: {e}")
            return None

    @staticmethod
    def end_span(span: Any) -> None:
        if span is None:
            return
        with contextlib.suppress(Exception):
            span.end()

    @staticmethod
    def update_span(
        span: Any,
        input: Any = None,
        output: Any = None,
        metadata: dict | None = None,
        usage_details: dict | None = None,
        cost_details: dict | None = None,
        model: str | None = None,
    ) -> None:
        if not span:
            return
        with contextlib.suppress(Exception):
            span.update(input=input, output=output, metadata=metadata)
            if usage_details is not None:
                span.update(usage_details=usage_details, cost_details=cost_details, model=model)

    # ------------------------------------------------------------------
    # Trace lifecycle
    # ------------------------------------------------------------------

    async def update_trace(
        self,
        trace_id: str,
        name: str | None = None,
        input: Any = None,
        output: Any = None,
        trace_params: dict | None = None,
    ) -> None:
        """Update trace attributes via Langfuse REST API. Called after SDK shutdown."""
        trace_params = trace_params or {}
        body: dict[str, Any] = {"id": trace_id}
        if name is not None:
            body["name"] = name
        if input is not None:
            body["input"] = input
        if output is not None:
            body["output"] = output
        key_map = {
            "session_id": "sessionId",
            "user_id": "userId",
            "metadata": "metadata",
            "tags": "tags",
            "input": "input",
            "output": "output",
        }
        for key, api_key in key_map.items():
            val = trace_params.get(key)
            if val is not None:
                body[api_key] = val
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self._host}/api/public/ingestion",
                    json={
                        "batch": [
                            {
                                "id": f"trace-update-{trace_id}",
                                "type": "trace-create",
                                "timestamp": datetime.now(UTC).isoformat(),
                                "body": body,
                            }
                        ]
                    },
                    auth=(self._public_key, self._secret_key),
                    timeout=5,
                )
        except Exception as e:
            logger.error(f"TRACING API: failed: {e}", exc_info=True)

    async def shutdown(self) -> None:
        if not self._langfuse:
            return
        try:
            self._langfuse.shutdown()
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"Error shutting down tracing: {e}")
