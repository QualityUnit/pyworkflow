"""
Token usage tracking for LLM calls within pyworkflow agents.

Provides a dataclass for accumulating token counts and a langchain callback
handler that automatically extracts usage from LLM responses.

Requires langchain-core to be installed:
    pip install 'pyworkflow-engine[agents]'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult


@dataclass
class TokenUsage:
    """
    Token usage counters for LLM calls.

    Supports addition for accumulating usage across multiple calls.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model: str | None = None

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            model=self.model or other.model,
        )

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens
        if self.model is None:
            self.model = other.model
        return self

    @classmethod
    def from_message(cls, message: AIMessage) -> TokenUsage:
        """Extract token usage from an AIMessage's usage_metadata."""
        meta = getattr(message, "usage_metadata", None)
        if meta is None:
            return cls()
        return cls(
            input_tokens=meta.get("input_tokens", 0),
            output_tokens=meta.get("output_tokens", 0),
            total_tokens=meta.get("total_tokens", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for pyworkflow events."""
        result: dict[str, Any] = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }
        if self.model is not None:
            result["model"] = self.model
        return result


class TokenUsageTracker(BaseCallbackHandler):
    """
    Langchain callback handler that tracks token usage across LLM calls.

    Usage:
        tracker = TokenUsageTracker()
        llm = ChatAnthropic(callbacks=[tracker])
        response = await llm.ainvoke(messages)
        print(tracker.total_usage)
    """

    def __init__(self) -> None:
        super().__init__()
        self.total_usage: TokenUsage = TokenUsage()
        self.call_usages: list[TokenUsage] = []

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Extract token usage from an LLM response."""
        usage = self._extract_from_llm_output(response)

        if usage is None:
            usage = self._extract_from_generations(response)

        if usage is not None:
            self.call_usages.append(usage)
            self.total_usage += usage

    def reset(self) -> None:
        """Clear all accumulated usage data."""
        self.total_usage = TokenUsage()
        self.call_usages = []

    def _extract_from_llm_output(self, response: LLMResult) -> TokenUsage | None:
        """Try to extract usage from llm_output (provider-specific formats)."""
        llm_output = response.llm_output
        if not llm_output:
            return None

        # OpenAI format: {"token_usage": {"prompt_tokens": ..., "completion_tokens": ...}}
        token_usage = llm_output.get("token_usage")
        if token_usage:
            input_t = token_usage.get("prompt_tokens", 0)
            output_t = token_usage.get("completion_tokens", 0)
            total_t = token_usage.get("total_tokens", input_t + output_t)
            model = llm_output.get("model_name")
            return TokenUsage(
                input_tokens=input_t,
                output_tokens=output_t,
                total_tokens=total_t,
                model=model,
            )

        # Anthropic format: {"usage": {"input_tokens": ..., "output_tokens": ...}}
        usage = llm_output.get("usage")
        if usage:
            input_t = usage.get("input_tokens", 0)
            output_t = usage.get("output_tokens", 0)
            total_t = input_t + output_t
            model = llm_output.get("model")
            return TokenUsage(
                input_tokens=input_t,
                output_tokens=output_t,
                total_tokens=total_t,
                model=model,
            )

        return None

    def _extract_from_generations(self, response: LLMResult) -> TokenUsage | None:
        """Fallback: extract usage from generation messages' usage_metadata."""
        for gen_list in response.generations:
            for gen in gen_list:
                message = getattr(gen, "message", None)
                if message is not None and isinstance(message, AIMessage):
                    usage = TokenUsage.from_message(message)
                    if usage.total_tokens > 0:
                        return usage
        return None
