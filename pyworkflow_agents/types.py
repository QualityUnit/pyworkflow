"""
Type aliases and re-exports for pyworkflow agents.

Requires langchain-core to be installed:
    pip install 'pyworkflow-engine[agents]'
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

ChatModel = BaseChatModel
"""Type alias for any langchain chat model (ChatAnthropic, ChatOpenAI, etc.)."""

MessageList = list[SystemMessage | HumanMessage | AIMessage | ToolMessage | BaseMessage]
"""Type alias for a list of chat messages."""

__all__ = [
    "ChatModel",
    "MessageList",
    "AIMessage",
    "HumanMessage",
    "SystemMessage",
    "ToolMessage",
    "BaseMessage",
]
