"""
Unit tests for workflow and step registry.
"""

import pytest

from pyworkflow.core.registry import (
    WorkflowRegistry,
    get_workflow,
    get_workflow_by_func,
    register_step,
    register_workflow,
)


class TestWorkflowRegistry:
    """Test the workflow registry functionality."""

    def test_register_and_get_workflow(self):
        """Test registering and retrieving a workflow."""
        registry = WorkflowRegistry()

        # Define a simple workflow function
        async def my_workflow():
            pass

        # Register workflow
        registry.register_workflow(
            name="test_workflow",
            func=my_workflow,
            original_func=my_workflow,
            max_duration="1h",
            tags=["backend", "critical"],
        )

        # Retrieve workflow
        workflow_meta = registry.get_workflow("test_workflow")

        assert workflow_meta is not None
        assert workflow_meta.name == "test_workflow"
        assert workflow_meta.func == my_workflow
        assert workflow_meta.max_duration == "1h"
        assert workflow_meta.tags == ["backend", "critical"]

    def test_get_workflow_by_func(self):
        """Test retrieving a workflow by its function reference."""
        registry = WorkflowRegistry()

        async def my_workflow():
            pass

        # Register workflow
        registry.register_workflow(
            name="test_workflow",
            func=my_workflow,
            original_func=my_workflow,
        )

        # Retrieve by function
        workflow_meta = registry.get_workflow_by_func(my_workflow)

        assert workflow_meta is not None
        assert workflow_meta.name == "test_workflow"

    def test_get_nonexistent_workflow(self):
        """Test retrieving a workflow that doesn't exist."""
        registry = WorkflowRegistry()
        workflow_meta = registry.get_workflow("nonexistent")
        assert workflow_meta is None

    def test_register_duplicate_workflow(self):
        """Test that registering the same workflow name raises an error."""
        registry = WorkflowRegistry()

        async def workflow1():
            pass

        async def workflow2():
            pass

        # Register first workflow
        registry.register_workflow(
            name="duplicate",
            func=workflow1,
            original_func=workflow1,
        )

        # Registering again should raise ValueError
        with pytest.raises(ValueError, match="already registered"):
            registry.register_workflow(
                name="duplicate",
                func=workflow2,
                original_func=workflow2,
            )

    def test_list_workflows(self):
        """Test listing all registered workflows."""
        registry = WorkflowRegistry()

        async def workflow1():
            pass

        async def workflow2():
            pass

        # Register multiple workflows
        registry.register_workflow(
            name="workflow_a",
            func=workflow1,
            original_func=workflow1,
        )
        registry.register_workflow(
            name="workflow_b",
            func=workflow2,
            original_func=workflow2,
        )

        workflows = registry.list_workflows()
        assert len(workflows) == 2
        assert "workflow_a" in workflows
        assert "workflow_b" in workflows


class TestStepRegistry:
    """Test the step registry functionality."""

    def test_register_and_get_step(self):
        """Test registering and retrieving a step."""
        registry = WorkflowRegistry()

        async def my_step():
            pass

        # Register step
        registry.register_step(
            name="test_step",
            func=my_step,
            original_func=my_step,
            max_retries=5,
            retry_delay="10",
            timeout=30,
            metadata={"type": "api_call"},
        )

        # Retrieve step
        step_meta = registry.get_step("test_step")

        assert step_meta is not None
        assert step_meta.name == "test_step"
        assert step_meta.func == my_step
        assert step_meta.max_retries == 5
        assert step_meta.retry_delay == "10"
        assert step_meta.timeout == 30
        assert step_meta.metadata == {"type": "api_call"}

    def test_get_nonexistent_step(self):
        """Test retrieving a step that doesn't exist."""
        registry = WorkflowRegistry()
        step_meta = registry.get_step("nonexistent")
        assert step_meta is None

    def test_register_duplicate_step(self):
        """Test that registering the same step name raises an error."""
        registry = WorkflowRegistry()

        async def step1():
            pass

        async def step2():
            pass

        # Register first step
        registry.register_step(
            name="duplicate",
            func=step1,
            original_func=step1,
        )

        # Registering again should raise ValueError
        with pytest.raises(ValueError, match="already registered"):
            registry.register_step(
                name="duplicate",
                func=step2,
                original_func=step2,
            )

    def test_list_steps(self):
        """Test listing all registered steps."""
        registry = WorkflowRegistry()

        async def step1():
            pass

        async def step2():
            pass

        # Register multiple steps
        registry.register_step(name="step_a", func=step1, original_func=step1)
        registry.register_step(name="step_b", func=step2, original_func=step2)

        steps = registry.list_steps()
        assert len(steps) == 2
        assert "step_a" in steps
        assert "step_b" in steps


class TestGlobalRegistry:
    """Test the global registry functions."""

    def test_register_workflow_globally(self):
        """Test the global register_workflow function."""

        async def global_workflow():
            pass

        register_workflow(
            name="global_test_workflow",
            func=global_workflow,
            original_func=global_workflow,
        )

        # Should be able to retrieve it
        workflow_meta = get_workflow("global_test_workflow")
        assert workflow_meta is not None
        assert workflow_meta.name == "global_test_workflow"

    def test_register_step_globally(self):
        """Test the global register_step function."""

        async def global_step():
            pass

        register_step(
            name="global_test_step",
            func=global_step,
            original_func=global_step,
        )

        # Should be able to retrieve it from global registry
        from pyworkflow.core.registry import _registry

        step_meta = _registry.get_step("global_test_step")
        assert step_meta is not None
        assert step_meta.name == "global_test_step"

    def test_get_workflow_by_func_globally(self):
        """Test retrieving workflow by function from global registry."""

        async def another_workflow():
            pass

        register_workflow(
            name="func_lookup_test",
            func=another_workflow,
            original_func=another_workflow,
        )

        # Should be able to retrieve by function
        workflow_meta = get_workflow_by_func(another_workflow)
        assert workflow_meta is not None
        assert workflow_meta.name == "func_lookup_test"
