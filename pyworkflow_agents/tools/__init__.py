"""
Tool framework for pyworkflow agents.

Provides a @tool decorator, ToolRegistry for managing tools, and
ToolDefinition/ToolResult types for introspection and execution results.

Requires langchain-core to be installed:
    pip install 'pyworkflow-engine[agents]'
"""

from pyworkflow_agents.tools.base import ToolDefinition, ToolResult
from pyworkflow_agents.tools.decorator import tool
from pyworkflow_agents.tools.registry import (
    ToolRegistry,
    get_global_registry,
    reset_global_registry,
)

__all__ = [
    "tool",
    "ToolRegistry",
    "ToolDefinition",
    "ToolResult",
    "get_global_registry",
    "reset_global_registry",
]
