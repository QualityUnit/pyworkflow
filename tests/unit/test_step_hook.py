"""Tests for step_hook() primitive."""

import contextlib

import pytest

from pyworkflow.context.base import reset_context, set_context
from pyworkflow.context.local import LocalContext
from pyworkflow.core.exceptions import SuspensionSignal
from pyworkflow.primitives.step_checkpoint import (
    reset_step_execution_context,
    set_step_execution_context,
)
from pyworkflow.primitives.step_hook import step_hook
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


class TestStepHook:
    """Tests for step_hook() primitive."""

    @pytest.mark.asyncio
    async def test_step_hook_creates_hook_and_suspends(self):
        """step_hook() should create hook and raise SuspensionSignal on first call."""
        storage = InMemoryStorageBackend()
        run_id = "test_run_1"

        run = WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        await storage.create_run(run)

        ctx = LocalContext(
            run_id=run_id, workflow_name="test_workflow", storage=storage, durable=True
        )
        ctx._is_step_worker = True
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            with pytest.raises(SuspensionSignal) as exc_info:
                await step_hook("human_review")

            assert exc_info.value.reason.startswith("step_hook:")
            assert "human_review" in exc_info.value.data["hook_id"]
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)

    @pytest.mark.asyncio
    async def test_step_hook_returns_payload_on_resume(self):
        """step_hook() should return cached payload when hook was already received."""
        storage = InMemoryStorageBackend()
        run_id = "test_run_1"

        run = WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        await storage.create_run(run)

        ctx = LocalContext(
            run_id=run_id, workflow_name="test_workflow", storage=storage, durable=True
        )
        ctx._is_step_worker = True
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            # First call - creates hook and suspends
            with contextlib.suppress(SuspensionSignal):
                await step_hook("review")

            # Simulate hook being received by recording HOOK_RECEIVED event
            from pyworkflow.engine.events import create_hook_received_event
            from pyworkflow.serialization.encoder import serialize

            payload = {"approved": True, "comment": "Looks good"}
            event = create_hook_received_event(
                run_id=run_id,
                hook_id="step_hook_review_0",
                payload=serialize(payload),
            )
            await storage.record_event(event)

            # Reset hook counter for re-execution simulation
            ctx._step_hook_counter = 0

            # Second call - should return the payload
            result = await step_hook("review")
            assert result == {"approved": True, "comment": "Looks good"}
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)

    @pytest.mark.asyncio
    async def test_step_hook_on_created_callback(self):
        """step_hook() should call on_created with the token."""
        storage = InMemoryStorageBackend()
        run_id = "test_run_1"

        run = WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        await storage.create_run(run)

        ctx = LocalContext(
            run_id=run_id, workflow_name="test_workflow", storage=storage, durable=True
        )
        ctx._is_step_worker = True
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            tokens = []

            async def on_created(token):
                tokens.append(token)

            with contextlib.suppress(SuspensionSignal):
                await step_hook("review", on_created=on_created)

            assert len(tokens) == 1
            assert run_id in tokens[0]
            assert "step_hook_review_0" in tokens[0]
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)

    @pytest.mark.asyncio
    async def test_step_hook_already_created_resuspends(self):
        """step_hook() should re-suspend if hook was created but not received."""
        storage = InMemoryStorageBackend()
        run_id = "test_run_1"

        run = WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        await storage.create_run(run)

        ctx = LocalContext(
            run_id=run_id, workflow_name="test_workflow", storage=storage, durable=True
        )
        ctx._is_step_worker = True
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            # First call - creates hook
            with contextlib.suppress(SuspensionSignal):
                await step_hook("review")

            # Reset counter for re-execution
            ctx._step_hook_counter = 0

            # Second call without HOOK_RECEIVED - should re-suspend
            with pytest.raises(SuspensionSignal):
                await step_hook("review")
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)

    @pytest.mark.asyncio
    async def test_step_hook_no_context_raises(self):
        """step_hook() should raise RuntimeError without workflow context."""
        with pytest.raises(RuntimeError, match="must be called within"):
            await step_hook("test")

    @pytest.mark.asyncio
    async def test_step_hook_deterministic_ids(self):
        """Multiple step_hook() calls should get sequential IDs."""
        storage = InMemoryStorageBackend()
        run_id = "test_run_1"

        run = WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        await storage.create_run(run)

        ctx = LocalContext(
            run_id=run_id, workflow_name="test_workflow", storage=storage, durable=True
        )
        ctx._is_step_worker = True
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            # First hook
            try:
                await step_hook("hook_a")
            except SuspensionSignal as e:
                assert e.data["hook_id"] == "step_hook_hook_a_0"

            # Reset counter and simulate first hook received
            ctx._step_hook_counter = 0

            from pyworkflow.engine.events import create_hook_received_event
            from pyworkflow.serialization.encoder import serialize

            event = create_hook_received_event(
                run_id=run_id,
                hook_id="step_hook_hook_a_0",
                payload=serialize({"ok": True}),
            )
            await storage.record_event(event)

            # Re-execute: first hook returns cached result
            result = await step_hook("hook_a")
            assert result == {"ok": True}

            # Second hook - new hook_id
            try:
                await step_hook("hook_b")
            except SuspensionSignal as e:
                assert e.data["hook_id"] == "step_hook_hook_b_1"
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)
