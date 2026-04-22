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
        model="gpt-4",
        llm_calls=[LLMCallData(input_tokens=100, output_tokens=50)],
    )
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LLMCallData(BaseModel):
    """Single LLM call trace data."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ToolCallData(BaseModel):
    """Single tool call trace data."""

    name: str = ""
    input: Any = None
    output: Any = None


class TracingStepResult(BaseModel):
    """
    Base class for step results that carry tracing metadata.

    Subclass this (alongside or instead of your own BaseModel) so that
    ``model_dump()`` automatically includes ``model``, ``llm_calls``,
    and ``tool_calls`` at the top level for PyWorkflow span creation.
    """

    model: str | None = None
    llm_calls: list[LLMCallData] = Field(default_factory=list)
    tool_calls: list[ToolCallData] = Field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.llm_calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.llm_calls)

    @property
    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self.llm_calls)
