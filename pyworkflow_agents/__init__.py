"""
PyWorkflow Agents - LLM provider abstraction for workflow-based AI agents.

This module provides type aliases, token tracking, and exceptions for integrating
LLM providers (via langchain-core) with pyworkflow agents.

Install as a separate package alongside pyworkflow:
    pip install 'pyworkflow-engine[agents]'

Exceptions are always importable. Types and token tracking require langchain-core.
"""

from pyworkflow_agents.exceptions import (
    AgentError,
    AgentPause,
    ProviderError,
    ProviderNotInstalledError,
)

__all__ = [
    # Exceptions (always available)
    "AgentError",
    "AgentPause",
    "ProviderError",
    "ProviderNotInstalledError",
]

try:
    from pyworkflow_agents.token_tracking import TokenUsage, TokenUsageTracker
    from pyworkflow_agents.types import (
        AIMessage,
        BaseMessage,
        ChatModel,
        HumanMessage,
        MessageList,
        SystemMessage,
        ToolMessage,
    )

    __all__ += [
        # Types (require langchain-core)
        "ChatModel",
        "MessageList",
        "AIMessage",
        "HumanMessage",
        "SystemMessage",
        "ToolMessage",
        "BaseMessage",
        # Token tracking (require langchain-core)
        "TokenUsage",
        "TokenUsageTracker",
    ]

    from pyworkflow_agents.tools import (
        ToolDefinition,
        ToolRegistry,
        ToolResult,
        get_global_registry,
        tool,
    )

    __all__ += [
        # Tools
        "tool",
        "ToolRegistry",
        "ToolDefinition",
        "ToolResult",
        "get_global_registry",
    ]

    from pyworkflow_agents.agent import (
        DEFAULT_SYSTEM_PROMPT,
        Agent,
        AgentResult,
        agent,
        run_agent_loop,
        run_tool_calling_loop,
        tool_calling_agent,
    )

    __all__ += [
        # Agent (explicit names)
        "DEFAULT_SYSTEM_PROMPT",
        "tool_calling_agent",
        "run_tool_calling_loop",
        "Agent",
        "AgentResult",
        # Agent (backward compatibility aliases)
        "agent",
        "run_agent_loop",
    ]
except ImportError:
    pass
