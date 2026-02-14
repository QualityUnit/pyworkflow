"""
AgentResult dataclass returned by the agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pyworkflow_agents.token_tracking import TokenUsage


@dataclass
class AgentResult:
    """Result of running an agent loop."""

    content: str
    messages: list = field(default_factory=list)
    tool_calls_made: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    iterations: int = 0
    finish_reason: str = "stop"
    agent_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "messages": [
                _message_to_dict(m) for m in self.messages
            ],
            "tool_calls_made": self.tool_calls_made,
            "token_usage": self.token_usage.to_dict(),
            "iterations": self.iterations,
            "finish_reason": self.finish_reason,
            "agent_id": self.agent_id,
        }


def _message_to_dict(msg: Any) -> dict[str, Any]:
    """Best-effort serialization of a langchain message."""
    if hasattr(msg, "dict"):
        return msg.dict()
    if hasattr(msg, "model_dump"):
        return msg.model_dump()
    return {"content": str(msg)}
