"""Tests for pyworkflow_agents import behavior and exception classes."""

import pytest


class TestExceptionsAlwaysImportable:
    """Exceptions must be importable without langchain-core."""

    def test_agent_error_importable(self):
        from pyworkflow_agents.exceptions import AgentError

        assert issubclass(AgentError, Exception)

    def test_provider_error_importable(self):
        from pyworkflow_agents.exceptions import ProviderError

        assert issubclass(ProviderError, Exception)

    def test_provider_not_installed_error_importable(self):
        from pyworkflow_agents.exceptions import ProviderNotInstalledError

        assert issubclass(ProviderNotInstalledError, Exception)

    def test_agent_error_inherits_workflow_error(self):
        from pyworkflow.core.exceptions import WorkflowError
        from pyworkflow_agents.exceptions import AgentError

        assert issubclass(AgentError, WorkflowError)

    def test_provider_error_inherits_agent_error(self):
        from pyworkflow_agents.exceptions import AgentError, ProviderError

        assert issubclass(ProviderError, AgentError)

    def test_provider_not_installed_inherits_provider_error(self):
        from pyworkflow_agents.exceptions import ProviderError, ProviderNotInstalledError

        assert issubclass(ProviderNotInstalledError, ProviderError)


class TestProviderError:
    def test_provider_attribute(self):
        from pyworkflow_agents.exceptions import ProviderError

        err = ProviderError("something went wrong", provider="anthropic")
        assert err.provider == "anthropic"
        assert "something went wrong" in str(err)

    def test_provider_attribute_default_none(self):
        from pyworkflow_agents.exceptions import ProviderError

        err = ProviderError("oops")
        assert err.provider is None


class TestProviderNotInstalledError:
    def test_message_contains_package_name(self):
        from pyworkflow_agents.exceptions import ProviderNotInstalledError

        err = ProviderNotInstalledError("anthropic", "langchain-anthropic")
        assert "langchain-anthropic" in str(err)

    def test_message_contains_pip_install_command(self):
        from pyworkflow_agents.exceptions import ProviderNotInstalledError

        err = ProviderNotInstalledError("openai", "langchain-openai")
        assert "pip install 'pyworkflow-engine[agents-openai]'" in str(err)

    def test_provider_attribute_set(self):
        from pyworkflow_agents.exceptions import ProviderNotInstalledError

        err = ProviderNotInstalledError("anthropic", "langchain-anthropic")
        assert err.provider == "anthropic"

    def test_package_attribute_set(self):
        from pyworkflow_agents.exceptions import ProviderNotInstalledError

        err = ProviderNotInstalledError("anthropic", "langchain-anthropic")
        assert err.package == "langchain-anthropic"


class TestInitImports:
    """Test that __init__.py exports work correctly."""

    def test_exceptions_importable_from_init(self):
        from pyworkflow_agents import AgentError, ProviderError, ProviderNotInstalledError

        assert AgentError is not None
        assert ProviderError is not None
        assert ProviderNotInstalledError is not None

    def test_types_importable_when_langchain_installed(self):
        pytest.importorskip("langchain_core")
        from pyworkflow_agents import ChatModel, MessageList

        assert ChatModel is not None
        assert MessageList is not None

    def test_token_tracking_importable_when_langchain_installed(self):
        pytest.importorskip("langchain_core")
        from pyworkflow_agents import TokenUsage, TokenUsageTracker

        assert TokenUsage is not None
        assert TokenUsageTracker is not None

    def test_message_types_importable_when_langchain_installed(self):
        pytest.importorskip("langchain_core")
        from pyworkflow_agents import (
            AIMessage,
            BaseMessage,
            HumanMessage,
            SystemMessage,
            ToolMessage,
        )

        assert AIMessage is not None
        assert HumanMessage is not None
        assert SystemMessage is not None
        assert ToolMessage is not None
        assert BaseMessage is not None

    def test_init_does_not_crash_without_langchain(self, monkeypatch):
        """Verify graceful degradation when langchain-core is not installed."""
        import importlib
        import sys

        # Remove cached agents module so it re-imports
        mods_to_remove = [k for k in sys.modules if k.startswith("pyworkflow_agents")]
        for mod in mods_to_remove:
            monkeypatch.delitem(sys.modules, mod)

        # Block langchain_core imports
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name.startswith("langchain_core"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        # Re-import — should not crash
        import pyworkflow_agents as agents_mod

        importlib.reload(agents_mod)

        # Exceptions still available
        assert hasattr(agents_mod, "AgentError")
        assert hasattr(agents_mod, "ProviderError")
        assert hasattr(agents_mod, "ProviderNotInstalledError")

        # Types not available (graceful degradation)
        assert "ChatModel" not in agents_mod.__all__
