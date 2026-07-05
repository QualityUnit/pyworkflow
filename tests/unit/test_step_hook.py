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


class TestStepHookTimeout:
    """Tests for step_hook() timeout semantics (on_timeout="return")."""

    def _make_ctx(self, storage, run_id):
        ctx = LocalContext(
            run_id=run_id, workflow_name="test_workflow", storage=storage, durable=True
        )
        ctx._is_step_worker = True
        return ctx

    @pytest.mark.asyncio
    async def test_first_call_with_timeout_return_carries_resume_at(self):
        """First call with on_timeout="return" suspends with the deadline in signal data."""
        from datetime import UTC, datetime

        storage = InMemoryStorageBackend()
        run_id = "test_run_to_1"
        await storage.create_run(
            WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        )
        ctx = self._make_ctx(storage, run_id)
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            before = datetime.now(UTC)
            with pytest.raises(SuspensionSignal) as exc_info:
                await step_hook("tick", timeout=60, on_timeout="return")
            resume_at = exc_info.value.data.get("resume_at")
            assert resume_at is not None
            delta = (resume_at - before).total_seconds()
            assert 55 <= delta <= 65
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)

    @pytest.mark.asyncio
    async def test_first_call_default_mode_has_no_resume_at(self):
        """Default on_timeout="suspend" keeps legacy behavior: no deadline resume."""
        storage = InMemoryStorageBackend()
        run_id = "test_run_to_2"
        await storage.create_run(
            WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        )
        ctx = self._make_ctx(storage, run_id)
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            with pytest.raises(SuspensionSignal) as exc_info:
                await step_hook("tick", timeout=60)
            assert exc_info.value.data.get("resume_at") is None
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)

    @pytest.mark.asyncio
    async def test_expired_hook_returns_sentinel(self):
        """Re-execution after the deadline returns STEP_HOOK_TIMEOUT (on_timeout="return")."""
        from datetime import UTC, datetime, timedelta

        from pyworkflow.engine.events import create_hook_created_event
        from pyworkflow.primitives.step_hook import STEP_HOOK_TIMEOUT, StepHookTimeout

        storage = InMemoryStorageBackend()
        run_id = "test_run_to_3"
        await storage.create_run(
            WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        )
        # Simulate a prior execution that created the hook with a now-past deadline
        await storage.record_event(
            create_hook_created_event(
                run_id=run_id,
                hook_id="step_hook_tick_0",
                token="tok",
                expires_at=datetime.now(UTC) - timedelta(seconds=5),
                name="tick",
            )
        )
        ctx = self._make_ctx(storage, run_id)
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            result = await step_hook("tick", timeout=60, on_timeout="return")
            assert result is STEP_HOOK_TIMEOUT
            assert isinstance(result, StepHookTimeout)
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)

    @pytest.mark.asyncio
    async def test_expired_hook_default_mode_resuspends(self):
        """Legacy mode keeps waiting: expired hook re-suspends without resume_at."""
        from datetime import UTC, datetime, timedelta

        from pyworkflow.engine.events import create_hook_created_event

        storage = InMemoryStorageBackend()
        run_id = "test_run_to_4"
        await storage.create_run(
            WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        )
        await storage.record_event(
            create_hook_created_event(
                run_id=run_id,
                hook_id="step_hook_tick_0",
                token="tok",
                expires_at=datetime.now(UTC) - timedelta(seconds=5),
                name="tick",
            )
        )
        ctx = self._make_ctx(storage, run_id)
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            with pytest.raises(SuspensionSignal) as exc_info:
                await step_hook("tick", timeout=60)
            assert exc_info.value.data.get("resume_at") is None
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)

    @pytest.mark.asyncio
    async def test_received_payload_wins_over_expiry(self):
        """A payload received before re-execution is returned even past the deadline."""
        from datetime import UTC, datetime, timedelta

        from pyworkflow.engine.events import (
            create_hook_created_event,
            create_hook_received_event,
        )
        from pyworkflow.serialization.encoder import serialize

        storage = InMemoryStorageBackend()
        run_id = "test_run_to_5"
        await storage.create_run(
            WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        )
        await storage.record_event(
            create_hook_created_event(
                run_id=run_id,
                hook_id="step_hook_tick_0",
                token="tok",
                expires_at=datetime.now(UTC) - timedelta(seconds=5),
                name="tick",
            )
        )
        await storage.record_event(
            create_hook_received_event(
                run_id=run_id,
                hook_id="step_hook_tick_0",
                payload=serialize({"index": 3}),
            )
        )
        ctx = self._make_ctx(storage, run_id)
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            result = await step_hook("tick", timeout=60, on_timeout="return")
            assert result == {"index": 3}
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)

    @pytest.mark.asyncio
    async def test_unexpired_hook_rearms_resume_at(self):
        """Re-execution before the deadline re-suspends carrying the original deadline."""
        from datetime import UTC, datetime, timedelta

        from pyworkflow.engine.events import create_hook_created_event

        storage = InMemoryStorageBackend()
        run_id = "test_run_to_6"
        await storage.create_run(
            WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        )
        deadline = datetime.now(UTC) + timedelta(seconds=120)
        await storage.record_event(
            create_hook_created_event(
                run_id=run_id,
                hook_id="step_hook_tick_0",
                token="tok",
                expires_at=deadline,
                name="tick",
            )
        )
        ctx = self._make_ctx(storage, run_id)
        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            with pytest.raises(SuspensionSignal) as exc_info:
                await step_hook("tick", timeout=60, on_timeout="return")
            resume_at = exc_info.value.data.get("resume_at")
            assert resume_at is not None
            assert abs((resume_at - deadline).total_seconds()) < 1
        finally:
            reset_step_execution_context(step_tokens)
            reset_context(ctx_token)
