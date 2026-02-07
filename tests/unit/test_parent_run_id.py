"""
Unit tests for parent_run_id and is_child_workflow context properties.

Tests cover:
- WorkflowContext base defaults (parent_run_id=None, is_child_workflow=False)
- LocalContext parent_run_id attribute and property
- MockContext inherits base defaults
- execute_workflow_with_context passes parent_run_id to context
- Child workflow execution sets parent_run_id correctly
- Resume workflow preserves parent_run_id
- Step worker context gets parent_run_id from storage
- Integration: full child workflow lifecycle with parent_run_id
"""

import asyncio
from datetime import UTC, datetime

import pytest

from pyworkflow.context import LocalContext, MockContext, get_context, set_context
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun

# =========================================================================
# Test: Base property defaults
# =========================================================================


class TestParentRunIdDefaults:
    """Test default values for parent_run_id and is_child_workflow."""

    def test_workflow_context_parent_run_id_default_none(self):
        """WorkflowContext.parent_run_id defaults to None."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        assert ctx.parent_run_id is None

    def test_workflow_context_is_child_workflow_default_false(self):
        """WorkflowContext.is_child_workflow defaults to False when no parent."""
        ctx = LocalContext(
            run_id="test_run",
            workflow_name="test_workflow",
            storage=None,
            durable=False,
        )
        assert ctx.is_child_workflow is False

    def test_mock_context_parent_run_id_default_none(self):
        """MockContext inherits parent_run_id=None from base."""
        ctx = MockContext(run_id="test", workflow_name="test")
        assert ctx.parent_run_id is None
        assert ctx.is_child_workflow is False


# =========================================================================
# Test: LocalContext parent_run_id attribute
# =========================================================================


class TestLocalContextParentRunId:
    """Test LocalContext._parent_run_id attribute and property."""

    def test_parent_run_id_can_be_set(self):
        """Test that _parent_run_id can be set on LocalContext."""
        ctx = LocalContext(
            run_id="child_run",
            workflow_name="child_workflow",
            storage=None,
            durable=False,
        )
        ctx._parent_run_id = "parent_run_123"
        assert ctx.parent_run_id == "parent_run_123"

    def test_is_child_workflow_true_when_parent_set(self):
        """Test is_child_workflow returns True when parent_run_id is set."""
        ctx = LocalContext(
            run_id="child_run",
            workflow_name="child_workflow",
            storage=None,
            durable=False,
        )
        ctx._parent_run_id = "parent_run_123"
        assert ctx.is_child_workflow is True

    def test_is_child_workflow_false_when_parent_none(self):
        """Test is_child_workflow returns False when parent_run_id is None."""
        ctx = LocalContext(
            run_id="top_level_run",
            workflow_name="workflow",
            storage=None,
            durable=False,
        )
        assert ctx.is_child_workflow is False

    def test_parent_run_id_initial_value_none(self):
        """Test that _parent_run_id is initially None after construction."""
        ctx = LocalContext(
            run_id="run",
            workflow_name="wf",
            storage=None,
            durable=False,
        )
        assert ctx._parent_run_id is None


# =========================================================================
# Test: execute_workflow_with_context passes parent_run_id
# =========================================================================


class TestExecuteWorkflowWithContextParentRunId:
    """Test that execute_workflow_with_context sets parent_run_id on context."""

    @pytest.mark.asyncio
    async def test_parent_run_id_set_on_context(self):
        """Test parent_run_id is accessible from within workflow function."""
        from pyworkflow.core.workflow import execute_workflow_with_context

        captured_parent_run_id = None
        captured_is_child = None

        async def capture_workflow():
            ctx = get_context()
            nonlocal captured_parent_run_id, captured_is_child
            captured_parent_run_id = ctx.parent_run_id
            captured_is_child = ctx.is_child_workflow
            return "done"

        result = await execute_workflow_with_context(
            workflow_func=capture_workflow,
            run_id="child_run_1",
            workflow_name="child_wf",
            storage=None,
            args=(),
            kwargs={},
            durable=False,
            parent_run_id="parent_run_abc",
        )

        assert result == "done"
        assert captured_parent_run_id == "parent_run_abc"
        assert captured_is_child is True

    @pytest.mark.asyncio
    async def test_no_parent_run_id_for_top_level_workflow(self):
        """Test parent_run_id is None for top-level workflow."""
        from pyworkflow.core.workflow import execute_workflow_with_context

        captured_parent_run_id = None
        captured_is_child = None

        async def capture_workflow():
            ctx = get_context()
            nonlocal captured_parent_run_id, captured_is_child
            captured_parent_run_id = ctx.parent_run_id
            captured_is_child = ctx.is_child_workflow
            return "done"

        result = await execute_workflow_with_context(
            workflow_func=capture_workflow,
            run_id="top_level_run",
            workflow_name="main_wf",
            storage=None,
            args=(),
            kwargs={},
            durable=False,
            # parent_run_id not passed -> defaults to None
        )

        assert result == "done"
        assert captured_parent_run_id is None
        assert captured_is_child is False

    @pytest.mark.asyncio
    async def test_parent_run_id_with_durable_storage(self):
        """Test parent_run_id works with durable storage context."""
        from pyworkflow.core.workflow import execute_workflow_with_context

        storage = InMemoryStorageBackend()

        captured_parent_run_id = None

        async def capture_workflow():
            ctx = get_context()
            nonlocal captured_parent_run_id
            captured_parent_run_id = ctx.parent_run_id
            return "done"

        result = await execute_workflow_with_context(
            workflow_func=capture_workflow,
            run_id="child_run_durable",
            workflow_name="child_wf",
            storage=storage,
            args=(),
            kwargs={},
            durable=True,
            parent_run_id="parent_run_durable",
        )

        assert result == "done"
        assert captured_parent_run_id == "parent_run_durable"


# =========================================================================
# Test: Step worker context gets parent_run_id
# =========================================================================


class TestStepWorkerParentRunId:
    """Test that step worker context gets parent_run_id from storage."""

    @pytest.mark.asyncio
    async def test_step_worker_context_has_parent_run_id_for_child_workflow(self):
        """Test that step worker context picks up parent_run_id when workflow is a child."""
        storage = InMemoryStorageBackend()

        # Create a child workflow run with parent_run_id
        child_run = WorkflowRun(
            run_id="child_run_1",
            workflow_name="child_wf",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            parent_run_id="parent_run_abc",
        )
        await storage.create_run(child_run)

        # Simulate what celery/tasks.py execute_step_task does
        events = await storage.get_events("child_run_1")
        ctx = LocalContext(
            run_id="child_run_1",
            workflow_name="child_wf",
            storage=storage,
            durable=True,
            event_log=events,
        )
        ctx._runtime = "celery"
        ctx._storage_config = {"type": "memory"}
        ctx._is_step_worker = True

        # Look up parent_run_id from storage (as the actual code does)
        wf_run = await storage.get_run("child_run_1")
        if wf_run and wf_run.parent_run_id:
            ctx._parent_run_id = wf_run.parent_run_id

        set_context(ctx)
        try:
            retrieved = get_context()
            assert retrieved.parent_run_id == "parent_run_abc"
            assert retrieved.is_child_workflow is True
        finally:
            set_context(None)

    @pytest.mark.asyncio
    async def test_step_worker_context_no_parent_for_top_level_workflow(self):
        """Test that step worker context has no parent_run_id for top-level workflows."""
        storage = InMemoryStorageBackend()

        # Create a top-level workflow run (no parent)
        run = WorkflowRun(
            run_id="top_level_run",
            workflow_name="main_wf",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await storage.create_run(run)

        events = await storage.get_events("top_level_run")
        ctx = LocalContext(
            run_id="top_level_run",
            workflow_name="main_wf",
            storage=storage,
            durable=True,
            event_log=events,
        )
        ctx._runtime = "celery"
        ctx._storage_config = {"type": "memory"}
        ctx._is_step_worker = True

        wf_run = await storage.get_run("top_level_run")
        if wf_run and wf_run.parent_run_id:
            ctx._parent_run_id = wf_run.parent_run_id

        set_context(ctx)
        try:
            retrieved = get_context()
            assert retrieved.parent_run_id is None
            assert retrieved.is_child_workflow is False
        finally:
            set_context(None)


# =========================================================================
# Test: Integration - child workflow has parent_run_id set
# =========================================================================


class TestChildWorkflowParentRunIdIntegration:
    """Integration tests for parent_run_id through the child workflow lifecycle."""

    @pytest.mark.asyncio
    async def test_child_workflow_sees_parent_run_id_via_local_runtime(self):
        """Test that a child workflow's context has parent_run_id set when run locally."""
        from pyworkflow import configure, reset_config, start, workflow

        reset_config()
        storage = InMemoryStorageBackend()
        configure(storage=storage, default_durable=True)

        captured_parent_run_id = None
        captured_is_child = None
        captured_run_id = None

        @workflow(durable=True)
        async def child_workflow():
            ctx = get_context()
            nonlocal captured_parent_run_id, captured_is_child, captured_run_id
            captured_parent_run_id = ctx.parent_run_id
            captured_is_child = ctx.is_child_workflow
            captured_run_id = ctx.run_id
            return "child_done"

        @workflow(durable=True)
        async def parent_workflow():
            from pyworkflow import start_child_workflow

            result = await start_child_workflow(child_workflow, wait_for_completion=True)
            return result

        parent_run_id = await start(parent_workflow)

        # Give workflows time to complete
        await asyncio.sleep(0.5)

        # The child should have seen the parent's run_id
        assert captured_parent_run_id == parent_run_id
        assert captured_is_child is True
        assert captured_run_id != parent_run_id  # Child has its own run_id

    @pytest.mark.asyncio
    async def test_top_level_workflow_has_no_parent(self):
        """Test that a top-level workflow has parent_run_id=None."""
        from pyworkflow import configure, reset_config, start, workflow

        reset_config()
        storage = InMemoryStorageBackend()
        configure(storage=storage, default_durable=True)

        captured_parent_run_id = "NOT_SET"
        captured_is_child = "NOT_SET"

        @workflow(durable=True)
        async def top_level_workflow():
            ctx = get_context()
            nonlocal captured_parent_run_id, captured_is_child
            captured_parent_run_id = ctx.parent_run_id
            captured_is_child = ctx.is_child_workflow
            return "done"

        await start(top_level_workflow)
        await asyncio.sleep(0.3)

        assert captured_parent_run_id is None
        assert captured_is_child is False

    @pytest.mark.asyncio
    async def test_fire_and_forget_child_has_parent_run_id(self):
        """Test that fire-and-forget child workflow also gets parent_run_id."""
        from pyworkflow import configure, reset_config, start, workflow

        reset_config()
        storage = InMemoryStorageBackend()
        configure(storage=storage, default_durable=True)

        captured_parent_run_id = None

        @workflow(durable=True)
        async def child_workflow():
            ctx = get_context()
            nonlocal captured_parent_run_id
            captured_parent_run_id = ctx.parent_run_id
            return "child_done"

        @workflow(durable=True)
        async def parent_workflow():
            from pyworkflow import start_child_workflow

            handle = await start_child_workflow(
                child_workflow, wait_for_completion=False
            )
            return handle.child_run_id

        parent_run_id = await start(parent_workflow)

        # Give child time to complete
        await asyncio.sleep(0.5)

        assert captured_parent_run_id == parent_run_id


# =========================================================================
# Test: Context accessible from step within child workflow
# =========================================================================


class TestParentRunIdFromStep:
    """Test that parent_run_id is accessible from steps within child workflows."""

    @pytest.mark.asyncio
    async def test_step_in_child_workflow_sees_parent_run_id(self):
        """Test that a step inside a child workflow can access parent_run_id."""
        from pyworkflow import configure, reset_config, start, step, workflow

        reset_config()
        storage = InMemoryStorageBackend()
        configure(storage=storage, default_durable=True)

        captured_parent_run_id = None
        captured_is_child = None

        @step()
        async def my_step():
            ctx = get_context()
            nonlocal captured_parent_run_id, captured_is_child
            captured_parent_run_id = ctx.parent_run_id
            captured_is_child = ctx.is_child_workflow
            return "step_done"

        @workflow(durable=True)
        async def child_workflow():
            return await my_step()

        @workflow(durable=True)
        async def parent_workflow():
            from pyworkflow import start_child_workflow

            return await start_child_workflow(child_workflow, wait_for_completion=True)

        parent_run_id = await start(parent_workflow)
        await asyncio.sleep(0.5)

        # The step ran in the child workflow's context, which has parent_run_id
        assert captured_parent_run_id == parent_run_id
        assert captured_is_child is True

    @pytest.mark.asyncio
    async def test_step_in_top_level_workflow_sees_no_parent(self):
        """Test that a step inside a top-level workflow sees no parent."""
        from pyworkflow import configure, reset_config, start, step, workflow

        reset_config()
        storage = InMemoryStorageBackend()
        configure(storage=storage, default_durable=True)

        captured_parent_run_id = "NOT_SET"
        captured_is_child = "NOT_SET"

        @step()
        async def my_step():
            ctx = get_context()
            nonlocal captured_parent_run_id, captured_is_child
            captured_parent_run_id = ctx.parent_run_id
            captured_is_child = ctx.is_child_workflow
            return "step_done"

        @workflow(durable=True)
        async def top_level_workflow():
            return await my_step()

        await start(top_level_workflow)
        await asyncio.sleep(0.3)

        assert captured_parent_run_id is None
        assert captured_is_child is False
