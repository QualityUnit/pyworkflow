"""
Tracing provider for PyWorkflow.

Creates and manages Langfuse tracing spans for workflow and step execution.
The provider is initialized from a tracing config dict passed via
``pyworkflow.start(tracing={...})`` or the ``@workflow(tracing={...})`` decorator.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from loguru import logger


class TracingProvider:
    """Manages a Langfuse client and the root workflow span."""

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

        self._root_span: Any = None
        self._root_span_id: Optional[str] = None
        self._trace_name: Optional[str] = None
        self._session_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Root (workflow-level) span
    # ------------------------------------------------------------------

    def start_root_span(
        self,
        name: str,
        trace_id: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Any:
        """Start the root workflow span on a fixed trace_id."""
        if not self._langfuse:
            return None
        self._trace_name = name
        self._session_id = session_id
        try:
            from langfuse import propagate_attributes

            with propagate_attributes(
                trace_name=name,
                session_id=session_id,
                user_id=user_id,
            ):
                self._root_span = self._langfuse.start_observation(
                    name=name, as_type="span",
                    trace_context={"trace_id": trace_id},
                )
            if self._root_span and hasattr(self._root_span, 'id'):
                self._root_span_id = self._root_span.id
            return self._root_span
        except Exception as e:
            logger.debug(f"Failed to start root span: {e}")
            return None

    def end_root_span(self) -> None:
        """End the root workflow span."""
        if self._root_span:
            try:
                self._root_span.end()
            except Exception:
                pass
            self._root_span = None

    # ------------------------------------------------------------------
    # Step-level spans
    # ------------------------------------------------------------------

    def start_step_span(self, name: str, is_generator: bool = False) -> Any:
        """Start a child span (or generation) nested under the root span."""
        if not self._langfuse:
            return None
        try:
            from opentelemetry.trace import use_span as otel_use_span

            as_type = "generation" if is_generator else "span"
            if self._root_span and hasattr(self._root_span, "_otel_span"):
                with otel_use_span(self._root_span._otel_span, end_on_exit=False):
                    return self._langfuse.start_observation(name=name, as_type=as_type)
            return self._langfuse.start_observation(name=name, as_type=as_type)
        except Exception as e:
            logger.debug(f"Failed to start step span: {e}")
            return None

    def start_child_span(self, parent_span: Any, name: str) -> Any:
        """Start a span nested under a given parent step span."""
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
        """Start a generation nested under a given parent step span."""
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

    def start_span_on_trace(self, trace_id: str, name: str, is_generator: bool = False, parent_span_id: Optional[str] = None, trace_name: Optional[str] = None) -> Any:
        """Start a span attached to a trace with optional parent span. For worker/resume step tracing."""
        if not self._langfuse:
            logger.info(f"TRACING SPAN: no langfuse client, skipping span {name}")
            return None
        try:
            from langfuse import propagate_attributes

            as_type = "generation" if is_generator else "span"
            trace_context = {"trace_id": trace_id}
            if parent_span_id:
                trace_context["parent_span_id"] = parent_span_id
            effective_trace_name = trace_name or self._trace_name or "workflow"
            logger.info(f"TRACING SPAN: creating {as_type} name={name}, trace_id={trace_id}, parent={parent_span_id}, trace_name={effective_trace_name}")
            with propagate_attributes(trace_name=effective_trace_name, session_id=self._session_id):
                span = self._langfuse.start_observation(
                    name=name, as_type=as_type,
                    trace_context=trace_context,
                )
            logger.info(f"TRACING SPAN: created span id={getattr(span, 'id', None)}")
            return span
        except Exception as e:
            logger.error(f"TRACING SPAN: failed to start span {name}: {e}", exc_info=True)
            return None

    @staticmethod
    def end_span(span: Any) -> None:
        """End a span or generation. No-op if None."""
        if span is None:
            return
        try:
            span.end()
        except Exception:
            pass

    @staticmethod
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
        if not span:
            return
        try:
            span.update(input=input, output=output, metadata=metadata)
            if usage_details is not None:
                span.update(usage_details=usage_details, cost_details=cost_details, model=model)
        except Exception:
            pass

    def update_root_trace(
        self,
        input: Any = None,
        output: Any = None,
    ) -> None:
        """Set trace-level input/output on the root span."""
        if self._root_span:
            try:
                self._root_span.set_trace_io(input=input, output=output)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def update_trace(self, trace_id: str, input: Any = None, output: Any = None) -> None:
        """Update trace-level input/output via Langfuse ingestion API."""
        if not self._langfuse:
            return
        try:
            self._langfuse._ingestion_consumer.add_task(
                {
                    "id": trace_id,
                    "type": "trace-create",
                    "timestamp": None,
                    "body": {
                        "id": trace_id,
                        "input": input,
                        "output": output,
                    },
                }
            )
        except Exception:
            pass

    async def shutdown(self) -> None:
        """Flush pending data and shut down the Langfuse client."""
        if not self._langfuse:
            return
        try:
            self._langfuse.shutdown()
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"Error shutting down tracing: {e}")

    async def update_trace_via_api(self, trace_id: str, name: str = None, input: Any = None, output: Any = None, trace_params: dict = None) -> None:
        """Update trace attributes via Langfuse REST API. Called after SDK shutdown."""
        trace_params = trace_params or {}
        body: dict[str, Any] = {"id": trace_id}
        if name is not None:
            body["name"] = name
        if input is not None:
            body["input"] = input
        if output is not None:
            body["output"] = output
        # Map trace_params keys to Langfuse API camelCase
        key_map = {"session_id": "sessionId", "user_id": "userId", "metadata": "metadata", "tags": "tags"}
        for key, api_key in key_map.items():
            val = trace_params.get(key)
            if val is not None:
                body[api_key] = val
        logger.info(f"TRACING API: host={self._host}, body_keys={list(body.keys())}, trace_params={trace_params}")
        try:
            import httpx
            from datetime import datetime, timezone
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._host}/api/public/ingestion",
                    json={"batch": [{"id": f"trace-update-{trace_id}", "type": "trace-create", "timestamp": datetime.now(timezone.utc).isoformat(), "body": body}]},
                    auth=(self._public_key, self._secret_key),
                    timeout=5,
                )
                logger.info(f"TRACING API: response status={resp.status_code}, body={resp.text[:500]}")
        except Exception as e:
            logger.error(f"TRACING API: failed: {e}", exc_info=True)

    @property
    def root_span(self) -> Any:
        return self._root_span


def create_tracing_provider(tracing_config: dict[str, Any] | None) -> TracingProvider | None:
    """Create a TracingProvider from a config dict. Returns None if config is None/empty."""
    if not tracing_config:
        return None
    provider = tracing_config.get("provider")
    if provider != "langfuse":
        logger.debug(f"Unknown tracing provider: {provider}")
        return None
    return TracingProvider(
        public_key=tracing_config.get("public_key", ""),
        secret_key=tracing_config.get("secret_key", ""),
        host=tracing_config.get("host", "https://app.langfuse.com"),
    )
