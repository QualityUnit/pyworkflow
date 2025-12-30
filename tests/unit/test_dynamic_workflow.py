"""
Unit tests for dynamic workflow code execution.

Tests the ability to execute dynamically generated workflow code.
"""

import pytest

from pyworkflow import configure, reset_config, start
from pyworkflow.celery.tasks import _register_dynamic_workflow
from pyworkflow.config import get_dynamic_workflow_imports
from pyworkflow.core.registry import get_workflow, _registry
from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


@pytest.fixture(autouse=True)
def reset_config_fixture():
    """Reset configuration before each test."""
    reset_config()
    # Clear any dynamically registered workflows
    workflows_to_remove = [
        name for name in _registry._workflows.keys()
        if name.startswith("dynamic_") or name.startswith("test_dynamic_")
    ]
    for name in workflows_to_remove:
        _registry._workflows.pop(name, None)
    yield
    reset_config()
    # Clean up again
    for name in workflows_to_remove:
        _registry._workflows.pop(name, None)


class TestDynamicWorkflowImportsConfig:
    """Test dynamic_workflow_imports configuration."""

    def test_default_imports_empty(self):
        """Test that default imports are empty."""
        imports = get_dynamic_workflow_imports()
        assert imports == {}

    def test_configure_dynamic_imports(self):
        """Test configuring dynamic workflow imports."""

        def my_helper():
            return "helper result"

        configure(
            dynamic_workflow_imports={
                "my_helper": my_helper,
                "custom_value": 42,
            }
        )

        imports = get_dynamic_workflow_imports()
        assert "my_helper" in imports
        assert "custom_value" in imports
        assert imports["my_helper"]() == "helper result"
        assert imports["custom_value"] == 42


class TestRegisterDynamicWorkflow:
    """Test _register_dynamic_workflow helper function."""

    def test_register_simple_workflow(self):
        """Test registering a simple dynamic workflow."""
        workflow_code = '''
@workflow(name="dynamic_simple_test")
async def dynamic_simple_test():
    return "hello"
'''
        workflow_meta = _register_dynamic_workflow("dynamic_simple_test", workflow_code)

        assert workflow_meta is not None
        assert workflow_meta.name == "dynamic_simple_test"

        # Verify it's in the registry
        registered = get_workflow("dynamic_simple_test")
        assert registered is not None
        assert registered.name == "dynamic_simple_test"

    def test_register_workflow_with_steps(self):
        """Test registering a workflow with step definitions."""
        workflow_code = '''
@step(name="dynamic_step")
async def dynamic_step(x: int):
    return x * 2

@workflow(name="dynamic_with_steps")
async def dynamic_with_steps(value: int):
    result = await dynamic_step(value)
    return result
'''
        workflow_meta = _register_dynamic_workflow("dynamic_with_steps", workflow_code)

        assert workflow_meta is not None
        assert workflow_meta.name == "dynamic_with_steps"

    def test_register_workflow_with_sleep(self):
        """Test registering a workflow that uses sleep primitive."""
        workflow_code = '''
@workflow(name="dynamic_with_sleep")
async def dynamic_with_sleep():
    await sleep("1s")
    return "done"
'''
        workflow_meta = _register_dynamic_workflow("dynamic_with_sleep", workflow_code)

        assert workflow_meta is not None
        assert workflow_meta.name == "dynamic_with_sleep"

    def test_register_workflow_not_found(self):
        """Test registering code that doesn't define the expected workflow."""
        workflow_code = '''
@workflow(name="wrong_name")
async def wrong_name():
    return "hello"
'''
        workflow_meta = _register_dynamic_workflow("expected_name", workflow_code)

        # Should return None because the workflow name doesn't match
        assert workflow_meta is None

    def test_register_workflow_invalid_code(self):
        """Test registering invalid Python code."""
        workflow_code = '''
this is not valid python code!!!
'''
        workflow_meta = _register_dynamic_workflow("invalid_workflow", workflow_code)

        assert workflow_meta is None

    def test_register_workflow_with_custom_imports(self):
        """Test registering a workflow with custom imports."""

        def custom_processor(x):
            return x * 10

        configure(
            dynamic_workflow_imports={
                "custom_processor": custom_processor,
            }
        )

        workflow_code = '''
@workflow(name="dynamic_custom_imports")
async def dynamic_custom_imports(value: int):
    return custom_processor(value)
'''
        workflow_meta = _register_dynamic_workflow("dynamic_custom_imports", workflow_code)

        assert workflow_meta is not None
        assert workflow_meta.name == "dynamic_custom_imports"

    def test_register_workflow_with_stdlib(self):
        """Test that registered workflows have access to common stdlib."""
        workflow_code = '''
@workflow(name="dynamic_stdlib")
async def dynamic_stdlib():
    import json as json_mod  # Already in namespace as 'json'
    data = {"key": "value"}
    return json.dumps(data)
'''
        workflow_meta = _register_dynamic_workflow("dynamic_stdlib", workflow_code)

        assert workflow_meta is not None

    def test_register_workflow_with_context(self):
        """Test that registered workflows can access context."""
        workflow_code = '''
@workflow(name="dynamic_context")
async def dynamic_context():
    if has_context():
        ctx = get_context()
        return ctx.run_id
    return "no context"
'''
        workflow_meta = _register_dynamic_workflow("dynamic_context", workflow_code)

        assert workflow_meta is not None


class TestDynamicWorkflowExecution:
    """Test executing dynamic workflows via start()."""

    @pytest.mark.asyncio
    async def test_start_with_workflow_code(self, tmp_path):
        """Test starting a workflow with workflow_code parameter."""
        workflow_code = '''
@workflow(name="test_dynamic_start")
async def test_dynamic_start(x: int, y: int):
    return x + y
'''
        # First register the workflow so we have the function
        _register_dynamic_workflow("test_dynamic_start", workflow_code)
        workflow_func = get_workflow("test_dynamic_start").func

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(
            workflow_func,
            5, 3,
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        # Check run was created
        assert run_id is not None

        # Check run status and workflow_code is stored
        run = await storage.get_run(run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.workflow_code == workflow_code

    @pytest.mark.asyncio
    async def test_dynamic_workflow_with_step(self, tmp_path):
        """Test dynamic workflow that includes step definitions."""
        workflow_code = '''
@step(name="test_dynamic_multiply")
async def test_dynamic_multiply(x: int):
    return x * 2

@workflow(name="test_dynamic_with_step")
async def test_dynamic_with_step(value: int):
    result = await test_dynamic_multiply(value)
    return result
'''
        _register_dynamic_workflow("test_dynamic_with_step", workflow_code)
        workflow_func = get_workflow("test_dynamic_with_step").func

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(
            workflow_func,
            10,
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        run = await storage.get_run(run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED


class TestWorkflowRunSchema:
    """Test WorkflowRun schema with workflow_code field."""

    def test_workflow_run_with_code(self):
        """Test creating WorkflowRun with workflow_code."""
        from datetime import datetime, UTC

        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            created_at=datetime.now(UTC),
            input_args="[]",
            input_kwargs="{}",
            workflow_code="@workflow\nasync def test(): pass",
        )

        assert run.workflow_code == "@workflow\nasync def test(): pass"

    def test_workflow_run_to_dict_includes_code(self):
        """Test that to_dict includes workflow_code."""
        from datetime import datetime, UTC

        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            created_at=datetime.now(UTC),
            input_args="[]",
            input_kwargs="{}",
            workflow_code="@workflow\nasync def test(): pass",
        )

        data = run.to_dict()
        assert "workflow_code" in data
        assert data["workflow_code"] == "@workflow\nasync def test(): pass"

    def test_workflow_run_from_dict_with_code(self):
        """Test that from_dict handles workflow_code."""
        from datetime import datetime, UTC

        now = datetime.now(UTC)
        data = {
            "run_id": "test_run",
            "workflow_name": "test_workflow",
            "status": "pending",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "input_args": "[]",
            "input_kwargs": "{}",
            "workflow_code": "@workflow\nasync def test(): pass",
        }

        run = WorkflowRun.from_dict(data)
        assert run.workflow_code == "@workflow\nasync def test(): pass"

    def test_workflow_run_without_code(self):
        """Test WorkflowRun without workflow_code (default None)."""
        from datetime import datetime, UTC

        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            created_at=datetime.now(UTC),
            input_args="[]",
            input_kwargs="{}",
        )

        assert run.workflow_code is None
