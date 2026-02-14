"""
Agent framework for pyworkflow — Agent base class, tool-calling agent, and more.

Requires langchain-core to be installed:
    pip install 'pyworkflow-engine[agents]'
"""

from pyworkflow_agents.agent.base import Agent
from pyworkflow_agents.agent.tool_calling import (
    DEFAULT_SYSTEM_PROMPT,
    run_tool_calling_loop,
    tool_calling_agent,
)
from pyworkflow_agents.agent.types import AgentResult

# Backward compatibility aliases — prefer the explicit names
agent = tool_calling_agent
run_agent_loop = run_tool_calling_loop

__all__ = [
    # Explicit names
    "DEFAULT_SYSTEM_PROMPT",
    "tool_calling_agent",
    "run_tool_calling_loop",
    # Shared
    "Agent",
    "AgentResult",
    # Backward compatibility aliases
    "agent",
    "run_agent_loop",
]
