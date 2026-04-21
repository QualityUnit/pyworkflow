"""
Tracing data structures for step results.

These dataclasses define the contract between PyWorkflow and integrating
applications (e.g. FlowHunt) for passing tracing metadata through step results.

Usage in integrating application::

    from pyworkflow.tracing.types import StepTracingData, LLMCallData, ToolCallData

    tracing_data = StepTracingData(
        credits=-1000,
        llm_calls=[LLMCallData(model="gpt-4", input_tokens=100, output_tokens=50, cost=0.01)],
        tool_calls=[ToolCallData(name="search", input="query", output="result", credits=-500)],
    )
    # Attach to step result dict:
    result["_tracing"] = tracing_data
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMCallData:
    """Single LLM call trace data."""

    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0


@dataclass
class ToolCallData:
    """Single tool call trace data."""

    name: str = ""
    input: Any = None
    output: Any = None
    duration_ms: int = 0
    credits: float = 0


@dataclass
class StepTracingData:
    """Tracing metadata attached to a step result for Langfuse span creation."""

    credits: float = 0
    llm_calls: list[LLMCallData] = field(default_factory=list)
    tool_calls: list[ToolCallData] = field(default_factory=list)
