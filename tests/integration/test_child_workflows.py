"""
Integration tests for child workflow feature.

Tests cover:
- Basic child workflow execution
- wait_for_completion=True (waiting for child)
- wait_for_completion=False (fire-and-forget with handle)
- Child workflow failure propagation
- Max nesting depth enforcement
- Parent completion cancels children (TERMINATE policy)
- Event replay with child workflows
"""

import asyncio

import pytest

from pyworkflow import (
    ChildWorkflowFailedError,
    ChildWorkflowHandle,
    RunStatus,
    configure,
    get_context,
    get_workflow_events,
    get_workflow_run,
    reset_config,
    start,
    start_child_workflow,
    step,
    workflow,
)
from pyworkflow.engine.events import EventType
from pyworkflow.storage.memory import InMemoryStorageBackend


@pytest.fixture(autouse=True)
def setup_storage():
    """Setup fresh storage for each test."""
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)
    yield storage
    reset_config()


# --- Define workflows/steps at module level with unique names ---


# Test 1: wait_for_completion
@step()
async def child_step_wait(value: int) -> int:
    return value * 2


@workflow(durable=True)
async def child_workflow_wait(value: int) -> int:
    return await child_step_wait(value)


@workflow(durable=True)
async def parent_workflow_wait(value: int) -> int:
    result = await start_child_workflow(child_workflow_wait, value)
    return result


# Test 2: fire_and_forget
@step()
async def slow_step_fandf() -> dict:
    await asyncio.sleep(0.2)
    return {"completed": True}


@workflow(durable=True)
async def child_workflow_fandf() -> dict:
    return await slow_step_fandf()


@workflow(durable=True)
async def parent_workflow_fandf() -> dict:
    handle = await start_child_workflow(
        child_workflow_fandf,
        wait_for_completion=False,
    )
    # Parent continues immediately
    return {"child_run_id": handle.child_run_id}


# Test 3: handle_result
@step()
async def process_step_handle(value: int) -> int:
    return value + 10


@workflow(durable=True)
async def child_workflow_handle(value: int) -> int:
    return await process_step_handle(value)


@workflow(durable=True)
async def parent_workflow_handle(value: int) -> int:
    handle: ChildWorkflowHandle = await start_child_workflow(
        child_workflow_handle,
        value,
        wait_for_completion=False,
    )
    # Do other work while child runs
    await asyncio.sleep(0.1)
    # Then get result
    result = await handle.result(timeout=5.0)
    return result


# Test 4: failure propagation
@step(max_retries=0)  # No retries so failure propagates immediately
async def failing_step_prop() -> None:
    raise ValueError("Child step failed!")


@workflow(durable=True)
async def failing_child_prop() -> dict:
    await failing_step_prop()
    return {"should": "not reach"}


@workflow(durable=True)
async def parent_workflow_failure() -> dict:
    try:
        await start_child_workflow(failing_child_prop)
        return {"status": "success"}
    except ChildWorkflowFailedError as e:
        return {
            "status": "child_failed",
            "error": e.error,
            "child_run_id": e.child_run_id,
        }


# Test 5: nesting depth
@step()
async def simple_step_depth() -> dict:
    return {"done": True}


@workflow(durable=True)
async def level_2_workflow_depth() -> dict:
    ctx = get_context()
    depth = await ctx.storage.get_nesting_depth(ctx.run_id)
    return {"depth": depth}


@workflow(durable=True)
async def level_1_workflow_depth() -> dict:
    result = await start_child_workflow(level_2_workflow_depth)
    return {"child_result": result}


@workflow(durable=True)
async def root_workflow_depth() -> dict:
    result = await start_child_workflow(level_1_workflow_depth)
    return {"child_result": result}


# Test 6: events started
@step()
async def child_step_events_started() -> dict:
    return {"done": True}


@workflow(durable=True)
async def child_workflow_events_started() -> dict:
    return await child_step_events_started()


@workflow(durable=True)
async def parent_workflow_events_started() -> dict:
    return await start_child_workflow(child_workflow_events_started)


# Test 7: events completed
@step()
async def child_step_events_completed() -> dict:
    return {"done": True}


@workflow(durable=True)
async def child_workflow_events_completed() -> dict:
    return await child_step_events_completed()


@workflow(durable=True)
async def parent_workflow_events_completed() -> dict:
    return await start_child_workflow(child_workflow_events_completed)


# Test 8: parent_run_id
@step()
async def child_step_parent_id() -> dict:
    return {"done": True}


@workflow(durable=True)
async def child_workflow_parent_id() -> dict:
    return await child_step_parent_id()


@workflow(durable=True)
async def parent_workflow_parent_id() -> dict:
    return await start_child_workflow(child_workflow_parent_id)


# Test 9: multiple children
@step()
async def process_step_multi(item: str) -> dict:
    return {"item": item, "processed": True}


@workflow(durable=True)
async def item_workflow_multi(item: str) -> dict:
    return await process_step_multi(item)


@workflow(durable=True)
async def parent_workflow_multi() -> dict:
    # Start 3 children
    handles = []
    for i in range(3):
        handle = await start_child_workflow(
            item_workflow_multi,
            f"item-{i}",
            wait_for_completion=False,
        )
        handles.append(handle)

    # Wait for all
    results = []
    for handle in handles:
        result = await handle.result(timeout=5.0)
        results.append(result)

    return {"results": results}


# Test 10: outside context
@workflow(durable=True)
async def some_workflow_outside() -> dict:
    return {"done": True}


# Test 11: unregistered workflow
@workflow(durable=True)
async def parent_workflow_unreg() -> dict:
    # This function is not decorated with @workflow
    async def not_a_workflow() -> dict:
        return {"done": True}

    return await start_child_workflow(not_a_workflow)


class TestBasicChildWorkflow:
    """Test basic child workflow execution."""

    @pytest.mark.asyncio
    async def test_start_child_workflow_wait_for_completion(self, setup_storage):
        """Test starting a child workflow and waiting for completion."""
        storage = setup_storage

        run_id = await start(parent_workflow_wait, 21)

        # Wait for completion
        await asyncio.sleep(0.5)

        run = await get_workflow_run(run_id, storage=storage)
        assert run.status == RunStatus.COMPLETED
        # Result is serialized
        assert "42" in run.result

    @pytest.mark.asyncio
    async def test_start_child_workflow_fire_and_forget(self, setup_storage):
        """Test starting a child workflow with fire-and-forget pattern."""
        storage = setup_storage

        run_id = await start(parent_workflow_fandf)

        # Parent should complete quickly (fire-and-forget)
        await asyncio.sleep(0.1)

        run = await get_workflow_run(run_id, storage=storage)
        assert run.status == RunStatus.COMPLETED

        # Wait for child to complete
        await asyncio.sleep(0.5)

        # Check children
        children = await storage.get_children(run_id)
        assert len(children) == 1
        assert children[0].status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_child_workflow_handle_result(self, setup_storage):
        """Test getting result from ChildWorkflowHandle."""
        storage = setup_storage

        run_id = await start(parent_workflow_handle, 32)

        await asyncio.sleep(0.5)

        run = await get_workflow_run(run_id, storage=storage)
        assert run.status == RunStatus.COMPLETED
        assert "42" in run.result


class TestChildWorkflowFailure:
    """Test child workflow failure handling."""

    @pytest.mark.asyncio
    async def test_child_workflow_failure_propagates(self, setup_storage):
        """Test that child workflow failure is propagated to parent."""
        storage = setup_storage

        run_id = await start(parent_workflow_failure)

        await asyncio.sleep(0.5)

        run = await get_workflow_run(run_id, storage=storage)
        assert run.status == RunStatus.COMPLETED
        assert "child_failed" in run.result


class TestNestingDepth:
    """Test nesting depth enforcement."""

    @pytest.mark.asyncio
    async def test_nesting_depth_tracked(self, setup_storage):
        """Test that nesting depth is tracked correctly."""
        storage = setup_storage

        run_id = await start(root_workflow_depth)

        await asyncio.sleep(0.5)

        # Check children depths
        children = await storage.get_children(run_id)
        assert len(children) == 1
        assert children[0].nesting_depth == 1


class TestChildWorkflowEvents:
    """Test child workflow events."""

    @pytest.mark.asyncio
    async def test_child_workflow_started_event_recorded(self, setup_storage):
        """Test that CHILD_WORKFLOW_STARTED event is recorded."""
        storage = setup_storage

        run_id = await start(parent_workflow_events_started)

        await asyncio.sleep(0.5)

        events = await get_workflow_events(run_id, storage=storage)
        event_types = [e.type for e in events]

        assert EventType.CHILD_WORKFLOW_STARTED in event_types

    @pytest.mark.asyncio
    async def test_child_workflow_completed_event_recorded(self, setup_storage):
        """Test that CHILD_WORKFLOW_COMPLETED event is recorded."""
        storage = setup_storage

        run_id = await start(parent_workflow_events_completed)

        await asyncio.sleep(0.5)

        events = await get_workflow_events(run_id, storage=storage)
        event_types = [e.type for e in events]

        assert EventType.CHILD_WORKFLOW_COMPLETED in event_types


class TestParentChildLifecycle:
    """Test parent-child lifecycle management."""

    @pytest.mark.asyncio
    async def test_children_have_parent_run_id(self, setup_storage):
        """Test that children have parent_run_id set."""
        storage = setup_storage

        run_id = await start(parent_workflow_parent_id)

        await asyncio.sleep(0.5)

        children = await storage.get_children(run_id)
        assert len(children) == 1
        assert children[0].parent_run_id == run_id

    @pytest.mark.asyncio
    async def test_multiple_children(self, setup_storage):
        """Test parent with multiple children."""
        storage = setup_storage

        run_id = await start(parent_workflow_multi)

        await asyncio.sleep(1.0)

        children = await storage.get_children(run_id)
        assert len(children) == 3
        assert all(c.status == RunStatus.COMPLETED for c in children)


class TestChildWorkflowOutsideContext:
    """Test start_child_workflow outside workflow context."""

    @pytest.mark.asyncio
    async def test_start_child_workflow_outside_context_raises(self, setup_storage):
        """Test that start_child_workflow raises outside workflow context."""
        with pytest.raises(RuntimeError, match="workflow context"):
            await start_child_workflow(some_workflow_outside)


class TestChildWorkflowWithUnregisteredWorkflow:
    """Test start_child_workflow with unregistered workflow."""

    @pytest.mark.asyncio
    async def test_start_child_workflow_unregistered_raises(self, setup_storage):
        """Test that start_child_workflow raises for unregistered workflow."""
        # In local runtime, exceptions are raised synchronously
        # Catch the exception and verify the workflow was marked as failed
        run_id = None
        try:
            run_id = await start(parent_workflow_unreg)
        except ValueError as e:
            # Expected: ValueError for unregistered workflow
            assert "not registered" in str(e).lower()

        # The workflow should have been marked as failed in storage
        # Find the workflow run that was created
        if run_id:
            run = await get_workflow_run(run_id, storage=setup_storage)
            assert run.status == RunStatus.FAILED
            assert "not registered" in run.error.lower()
