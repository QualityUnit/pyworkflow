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
    ProviderError,
    ProviderNotInstalledError,
)

__all__ = [
    # Exceptions (always available)
    "AgentError",
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
except ImportError:
    pass
