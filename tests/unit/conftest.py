"""
Test configuration and fixtures for unit tests.
"""

import pytest


@pytest.fixture(autouse=True)
def reset_global_registry():
    """Reset the global registry before each test to ensure test isolation."""
    from pyworkflow.core.registry import _registry

    # Store original state
    original_workflows = _registry._workflows.copy()
    original_steps = _registry._steps.copy()

    # Clear registry for test
    _registry._workflows.clear()
    _registry._steps.clear()

    yield

    # Restore original state (or clear again)
    _registry._workflows.clear()
    _registry._steps.clear()
    _registry._workflows.update(original_workflows)
    _registry._steps.update(original_steps)


@pytest.fixture(autouse=True)
def reset_workflow_context():
    """Ensure no workflow context leaks between tests."""
    from pyworkflow.context import set_context

    # Clear any existing context before test
    set_context(None)

    yield

    # Clear context after test
    set_context(None)
