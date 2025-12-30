"""
Integration tests for dynamic workflow code execution.

Tests end-to-end dynamic workflow execution with various storage backends.
"""

import pytest

from pyworkflow import (
    configure,
    get_workflow_events,
    get_workflow_run,
    reset_config,
    resume,
    start,
)
from pyworkflow.celery.tasks import _register_dynamic_workflow
from pyworkflow.core.registry import get_workflow, _registry
from pyworkflow.engine.events import EventType
from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus


@pytest.fixture(autouse=True)
def reset_config_fixture():
    """Reset configuration before each test."""
    reset_config()
    # Clear any dynamically registered workflows
    workflows_to_remove = [
        name for name in list(_registry._workflows.keys())
        if name.startswith("dynamic_") or name.startswith("integ_")
    ]
    for name in workflows_to_remove:
        _registry._workflows.pop(name, None)
    yield
    reset_config()
    # Clean up again
    for name in list(_registry._workflows.keys()):
        if name.startswith("dynamic_") or name.startswith("integ_"):
            _registry._workflows.pop(name, None)


class TestDynamicWorkflowWithInMemoryStorage:
    """Test dynamic workflows with InMemoryStorageBackend."""

    @pytest.mark.asyncio
    async def test_simple_dynamic_workflow(self):
        """Test executing a simple dynamic workflow."""
        workflow_code = '''
@workflow(name="integ_simple")
async def integ_simple(name: str):
    return f"Hello, {name}!"
'''
        _register_dynamic_workflow("integ_simple", workflow_code)
        workflow_func = get_workflow("integ_simple").func

        storage = InMemoryStorageBackend()
        configure(storage=storage, default_durable=True)

        run_id = await start(
            workflow_func,
            "World",
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        run = await get_workflow_run(run_id, storage=storage)
        assert run.status == RunStatus.COMPLETED
        assert run.workflow_code == workflow_code

    @pytest.mark.asyncio
    async def test_dynamic_workflow_with_multiple_steps(self):
        """Test dynamic workflow with multiple step definitions."""
        workflow_code = '''
@step(name="integ_add")
async def integ_add(a: int, b: int) -> int:
    return a + b

@step(name="integ_multiply")
async def integ_multiply(x: int, factor: int) -> int:
    return x * factor

@workflow(name="integ_multi_step")
async def integ_multi_step(a: int, b: int, factor: int):
    sum_result = await integ_add(a, b)
    final = await integ_multiply(sum_result, factor)
    return final
'''
        _register_dynamic_workflow("integ_multi_step", workflow_code)
        workflow_func = get_workflow("integ_multi_step").func

        storage = InMemoryStorageBackend()
        configure(storage=storage, default_durable=True)

        run_id = await start(
            workflow_func,
            5, 3, 2,
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        run = await get_workflow_run(run_id, storage=storage)
        assert run.status == RunStatus.COMPLETED

        # Check events were recorded
        events = await get_workflow_events(run_id, storage=storage)
        step_completed_events = [e for e in events if e.type == EventType.STEP_COMPLETED]
        assert len(step_completed_events) == 2

    @pytest.mark.asyncio
    async def test_dynamic_workflow_events(self):
        """Test that dynamic workflows properly record events."""
        workflow_code = '''
@step(name="integ_process")
async def integ_process(data: str) -> dict:
    return {"processed": data}

@workflow(name="integ_events")
async def integ_events(input_data: str):
    result = await integ_process(input_data)
    return result
'''
        _register_dynamic_workflow("integ_events", workflow_code)
        workflow_func = get_workflow("integ_events").func

        storage = InMemoryStorageBackend()
        configure(storage=storage, default_durable=True)

        run_id = await start(
            workflow_func,
            "test-data",
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        events = await get_workflow_events(run_id, storage=storage)

        # Should have workflow_started, step_completed, and workflow_completed
        event_types = [e.type for e in events]
        assert EventType.WORKFLOW_STARTED in event_types
        assert EventType.STEP_COMPLETED in event_types


class TestDynamicWorkflowWithFileStorage:
    """Test dynamic workflows with FileStorageBackend."""

    @pytest.mark.asyncio
    async def test_dynamic_workflow_persists(self, tmp_path):
        """Test that dynamic workflow code is persisted in file storage."""
        workflow_code = '''
@workflow(name="integ_persist")
async def integ_persist(value: int):
    return value * 2
'''
        _register_dynamic_workflow("integ_persist", workflow_code)
        workflow_func = get_workflow("integ_persist").func

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(
            workflow_func,
            42,
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        # Create a new storage instance to simulate restart
        storage2 = FileStorageBackend(base_path=str(tmp_path))
        run = await storage2.get_run(run_id)

        assert run is not None
        assert run.workflow_code == workflow_code
        assert run.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_dynamic_workflow_with_custom_imports(self, tmp_path):
        """Test dynamic workflow using custom configured imports."""

        def custom_transform(data):
            return {"transformed": data, "by": "custom_transform"}

        configure(
            dynamic_workflow_imports={
                "custom_transform": custom_transform,
            }
        )

        workflow_code = '''
@workflow(name="integ_custom_imports")
async def integ_custom_imports(input_data: str):
    result = custom_transform(input_data)
    return result
'''
        _register_dynamic_workflow("integ_custom_imports", workflow_code)
        workflow_func = get_workflow("integ_custom_imports").func

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(
            workflow_func,
            "test",
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        run = await storage.get_run(run_id)
        assert run.status == RunStatus.COMPLETED


class TestDynamicWorkflowWithSuspension:
    """Test dynamic workflows that suspend and resume."""

    @pytest.mark.asyncio
    async def test_dynamic_workflow_with_sleep(self, tmp_path):
        """Test dynamic workflow that uses sleep (suspension)."""
        workflow_code = '''
@workflow(name="integ_with_sleep")
async def integ_with_sleep():
    await sleep("0s")  # Immediate sleep
    return "done"
'''
        _register_dynamic_workflow("integ_with_sleep", workflow_code)
        workflow_func = get_workflow("integ_with_sleep").func

        storage = FileStorageBackend(base_path=str(tmp_path))
        run_id = await start(
            workflow_func,
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        # With 0s sleep, should complete immediately (or suspend and resume)
        run = await storage.get_run(run_id)
        # The workflow should either complete or be suspended
        assert run.status in [RunStatus.COMPLETED, RunStatus.SUSPENDED]

        # If suspended, resume it
        if run.status == RunStatus.SUSPENDED:
            await resume(run_id, storage=storage)
            run = await storage.get_run(run_id)
            assert run.status == RunStatus.COMPLETED


class TestDynamicWorkflowErrorHandling:
    """Test error handling in dynamic workflows."""

    @pytest.mark.asyncio
    async def test_dynamic_workflow_failure(self, tmp_path):
        """Test dynamic workflow that raises an error."""
        workflow_code = '''
@workflow(name="integ_failing")
async def integ_failing():
    raise ValueError("Dynamic workflow error")
'''
        _register_dynamic_workflow("integ_failing", workflow_code)
        workflow_func = get_workflow("integ_failing").func

        storage = FileStorageBackend(base_path=str(tmp_path))

        with pytest.raises(ValueError, match="Dynamic workflow error"):
            await start(
                workflow_func,
                durable=True,
                storage=storage,
                workflow_code=workflow_code,
            )

        # Find the run (it should be marked as failed)
        runs, _ = await storage.list_runs(limit=1)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_dynamic_step_failure(self, tmp_path):
        """Test dynamic workflow with a failing step."""
        workflow_code = '''
@step(name="integ_failing_step")
async def integ_failing_step():
    raise FatalError("Step failure")

@workflow(name="integ_step_fail")
async def integ_step_fail():
    await integ_failing_step()
    return "should not reach"
'''
        _register_dynamic_workflow("integ_step_fail", workflow_code)
        workflow_func = get_workflow("integ_step_fail").func

        storage = FileStorageBackend(base_path=str(tmp_path))

        with pytest.raises(Exception):  # FatalError
            await start(
                workflow_func,
                durable=True,
                storage=storage,
                workflow_code=workflow_code,
            )


class TestDynamicWorkflowWithConditionalLogic:
    """Test dynamic workflows with conditional logic."""

    @pytest.mark.asyncio
    async def test_dynamic_workflow_with_conditions(self, tmp_path):
        """Test dynamic workflow with if/else logic."""
        workflow_code = '''
@step(name="integ_check")
async def integ_check(value: int) -> bool:
    return value > 10

@step(name="integ_process_high")
async def integ_process_high(value: int) -> str:
    return f"HIGH: {value}"

@step(name="integ_process_low")
async def integ_process_low(value: int) -> str:
    return f"LOW: {value}"

@workflow(name="integ_conditional")
async def integ_conditional(value: int):
    is_high = await integ_check(value)
    if is_high:
        result = await integ_process_high(value)
    else:
        result = await integ_process_low(value)
    return result
'''
        _register_dynamic_workflow("integ_conditional", workflow_code)
        workflow_func = get_workflow("integ_conditional").func

        storage = FileStorageBackend(base_path=str(tmp_path))

        # Test high value path
        run_id = await start(
            workflow_func,
            15,
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        run = await storage.get_run(run_id)
        assert run.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_dynamic_workflow_with_loop(self, tmp_path):
        """Test dynamic workflow with loop logic."""
        workflow_code = '''
@step(name="integ_increment")
async def integ_increment(value: int) -> int:
    return value + 1

@workflow(name="integ_loop")
async def integ_loop(start_value: int, iterations: int):
    value = start_value
    for _ in range(iterations):
        value = await integ_increment(value)
    return value
'''
        _register_dynamic_workflow("integ_loop", workflow_code)
        workflow_func = get_workflow("integ_loop").func

        storage = FileStorageBackend(base_path=str(tmp_path))

        run_id = await start(
            workflow_func,
            0, 3,  # Start at 0, increment 3 times
            durable=True,
            storage=storage,
            workflow_code=workflow_code,
        )

        run = await storage.get_run(run_id)
        assert run.status == RunStatus.COMPLETED

        # Check we have 3 step completed events
        events = await storage.get_events(run_id)
        step_events = [e for e in events if e.type == EventType.STEP_COMPLETED]
        assert len(step_events) == 3
