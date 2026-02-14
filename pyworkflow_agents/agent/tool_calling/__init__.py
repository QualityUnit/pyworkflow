"""
Tool-calling agent — decorator and loop for agents that use model.bind_tools().
"""

from pyworkflow_agents.agent.tool_calling.decorator import tool_calling_agent
from pyworkflow_agents.agent.tool_calling.loop import DEFAULT_SYSTEM_PROMPT, run_tool_calling_loop

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "tool_calling_agent",
    "run_tool_calling_loop",
]
