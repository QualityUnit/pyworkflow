"""
Base dataclasses for tool definitions and execution results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolDefinition:
    """Describes a tool's interface (name, description, JSON Schema parameters)."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class ToolResult:
    """Result of executing a tool, including timing and error information."""

    tool_name: str
    tool_call_id: str
    result: Any
    error: str | None = None
    duration_ms: float = 0.0
    is_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "is_error": self.is_error,
        }
