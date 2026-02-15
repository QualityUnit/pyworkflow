"""
Exception classes for pyworkflow agents.

These exceptions are always importable — they do not depend on langchain-core
or any optional provider packages.
"""

from pyworkflow.core.exceptions import WorkflowError


class AgentError(WorkflowError):
    """Base exception for all agent-related errors."""

    pass


class ProviderError(AgentError):
    """
    Error originating from an LLM provider.

    Attributes:
        provider: Name of the provider that raised the error (e.g. "anthropic", "openai").
    """

    def __init__(self, message: str, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class AgentPause:
    """Sentinel returned by on_agent_action to trigger durable pause.

    When an ``on_agent_action`` callback returns an ``AgentPause`` instance,
    the agent loop will suspend the workflow via a hook (durable mode) or
    return a partial ``AgentResult`` (standalone mode).
    """

    def __init__(self, reason: str = "user_requested") -> None:
        self.reason = reason


class ProviderNotInstalledError(ProviderError):
    """
    Raised when the required LLM provider package is not installed.

    Provides a clear pip install command so the user can resolve the issue.
    """

    def __init__(self, provider: str, package: str) -> None:
        install_cmd = f"pip install 'pyworkflow-engine[agents-{provider}]'"
        super().__init__(
            f"LLM provider '{provider}' requires the '{package}' package. "
            f"Install it with: {install_cmd}",
            provider=provider,
        )
        self.package = package
