"""
ToolRegistry for managing and executing tools.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.tools import BaseTool

from pyworkflow_agents.tools.base import ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry that stores, looks up, and executes tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool. Logs a warning and replaces on duplicate name."""
        if tool.name in self._tools:
            logger.warning("Duplicate tool name '%s'; replacing existing tool.", tool.name)
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Remove a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def get_all(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def get_definitions(self) -> list[ToolDefinition]:
        """Return a ToolDefinition for each registered tool."""
        return [
            ToolDefinition(
                name=t.name,
                description=t.description,
                parameters=t.args,
            )
            for t in self._tools.values()
        ]

    async def execute(
        self, tool_name: str, tool_args: dict[str, Any], tool_call_id: str = ""
    ) -> ToolResult:
        """Execute a tool by name with the given arguments.

        Args:
            tool_name: Name of the tool to execute.
            tool_args: Keyword arguments to pass to the tool.
            tool_call_id: Optional identifier for the tool call.

        Returns:
            ToolResult with the outcome, timing, and any error information.

        Raises:
            KeyError: If tool_name is not registered.
        """
        t = self._tools.get(tool_name)
        if t is None:
            raise KeyError(f"Tool '{tool_name}' not found in registry.")

        start = time.perf_counter()
        try:
            result = await t.ainvoke(tool_args)
            duration_ms = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result=result,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result=None,
                error=str(exc),
                duration_ms=duration_ms,
                is_error=True,
            )

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


_global_registry: ToolRegistry | None = None


def get_global_registry() -> ToolRegistry:
    """Return the global ToolRegistry singleton, creating it lazily."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def reset_global_registry() -> None:
    """Reset the global registry (useful for testing)."""
    global _global_registry
    _global_registry = None
