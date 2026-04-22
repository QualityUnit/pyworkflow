"""
Tracing data structures for step results.

These types define the contract between PyWorkflow and integrating
applications (e.g. FlowHunt) for passing tracing metadata through step results.

Usage in integrating application::

    from pyworkflow.tracing.types import TracingStepResult, LLMCallData, ToolCallData

    class MyStepResult(TracingStepResult):
        vertex_id: str
        text_output: str

    result = MyStepResult(
        vertex_id="v1",
        text_output="hello",
        credits=-1000,
        llm_calls=[LLMCallData(model="gpt-4", input_tokens=100, output_tokens=50, cost=0.01)],
    )
"""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, Field


class LLMCallData(BaseModel):
    """Single LLM call trace data."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0


class ToolCallData(BaseModel):
    """Single tool call trace data."""

    name: str = ""
    input: Any = None
    output: Any = None
    duration_ms: int = 0
    credits: float = 0


class TracingStepResult(BaseModel):
    """
    Base class for step results that carry tracing metadata.

    Subclass this (alongside or instead of your own BaseModel) so that
    ``model_dump()`` automatically includes ``credits``, ``llm_calls``,
    and ``tool_calls`` at the top level for PyWorkflow span creation.
    """

    credits: float = 0
    model: str | None = None
    llm_calls: List[LLMCallData] = Field(default_factory=list)
    tool_calls: List[ToolCallData] = Field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.llm_calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.llm_calls)

    @property
    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self.llm_calls)

    @property
    def total_cost(self) -> float:
        return sum(c.cost for c in self.llm_calls)

    def to_dict(self) -> dict[str, Any]:
        """Serialize tracing fields for embedding in step result dicts."""
        return {
            "credits": self.credits,
            "model": self.model,
            "llm_calls": [
                {
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "total_tokens": c.total_tokens,
                    "cost": c.cost,
                }
                for c in self.llm_calls
            ],
            "tool_calls": [
                {
                    "name": c.name,
                    "input": c.input,
                    "output": c.output,
                    "duration_ms": c.duration_ms,
                    "credits": c.credits,
                }
                for c in self.tool_calls
            ],
        }
