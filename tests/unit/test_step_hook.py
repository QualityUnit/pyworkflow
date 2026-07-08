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


class TestStepHookInlineSuspension:
    """End-to-end tests for step_hook() suspension on the inline (local runtime) path.

    Regression coverage for the bug where a step suspending via step_hook() on the
    inline path recorded no STEP_SUSPENDED event, so replay saw the step's
    STEP_STARTED without a STEP_SUSPENDED, treated it as still in progress, and
    re-suspended forever.
    """

    @pytest.mark.asyncio
    async def test_local_runtime_completes_after_resume_hook(self):
        """A local-runtime step that suspends via step_hook() completes after resume."""
        from pyworkflow import configure, reset_config, start
        from pyworkflow.core.step import step
        from pyworkflow.core.workflow import workflow
        from pyworkflow.primitives.resume_hook import create_hook_token, resume_hook
        from pyworkflow.primitives.step_hook import step_hook
        from pyworkflow.serialization.decoder import deserialize_args

        reset_config()

        @step(name="inline_review_step")
        async def review_step():
            feedback = await step_hook("review")
            return {"feedback": feedback}

        @workflow(name="inline_review_workflow")
        async def review_workflow():
            return await review_step()

        try:
            storage = InMemoryStorageBackend()
            configure(storage=storage)
            run_id = await start(review_workflow, durable=True, storage=storage)

            # The workflow suspends waiting for the hook.
            run = await storage.get_run(run_id)
            assert run.status == RunStatus.SUSPENDED

            # A STEP_SUSPENDED event must be recorded on the inline path so that
            # replay does not treat the step as still in progress.
            from pyworkflow.engine.events import EventType

            events = await storage.get_events(run_id)
            suspended = [e for e in events if e.type == EventType.STEP_SUSPENDED]
            assert len(suspended) == 1, "STEP_SUSPENDED must be recorded on the inline path"

            # Deliver the external answer. resume_hook() drives the local runtime
            # to resume the workflow synchronously.
            token = create_hook_token(run_id, "step_hook_review_0")
            await resume_hook(token, {"approved": True}, storage=storage)

            # The run must now be COMPLETE and carry the payload returned by step_hook().
            run = await storage.get_run(run_id)
            assert run.status == RunStatus.COMPLETED, (
                f"run should be COMPLETED after resume, got {run.status}"
            )
            result = deserialize_args(run.result)[0]
            assert result == {"feedback": {"approved": True}}
        finally:
            reset_config()

    @pytest.mark.asyncio
    async def test_crash_replay_reexecutes_without_duplicate_hook(self):
        """After suspension, a fresh executor replay re-executes the step and
        completes once resumed, without re-creating the visitor-facing hook."""
        from pyworkflow import configure, reset_config, resume, start
        from pyworkflow.core.step import step
        from pyworkflow.core.workflow import workflow
        from pyworkflow.engine.events import EventType
        from pyworkflow.primitives.step_hook import step_hook
        from pyworkflow.serialization.decoder import deserialize_args

        reset_config()

        body_executions = 0
        on_created_calls = 0

        @step(name="crash_replay_step")
        async def review_step():
            nonlocal body_executions
            body_executions += 1

            async def notify(_token):
                nonlocal on_created_calls
                on_created_calls += 1

            feedback = await step_hook("approval", on_created=notify)
            return {"feedback": feedback, "runs": body_executions}

        @workflow(name="crash_replay_workflow")
        async def review_workflow():
            return await review_step()

        try:
            storage = InMemoryStorageBackend()
            configure(storage=storage)
            run_id = await start(review_workflow, durable=True, storage=storage)

            assert body_executions == 1
            assert on_created_calls == 1
            run = await storage.get_run(run_id)
            assert run.status == RunStatus.SUSPENDED

            # Simulate delivery of the hook WITHOUT the local runtime auto-resuming
            # (i.e. crash between resume_hook recording and resume). Record the
            # HOOK_RECEIVED event directly.
            from pyworkflow.engine.events import create_hook_received_event
            from pyworkflow.serialization.encoder import serialize

            hook_id = "step_hook_approval_0"
            await storage.record_event(
                create_hook_received_event(
                    run_id=run_id,
                    hook_id=hook_id,
                    payload=serialize({"approved": True}),
                )
            )

            # Fresh executor replays from the event log and resumes.
            resume_result = await resume(run_id, storage=storage)
            assert resume_result["feedback"] == {"approved": True}

            # The step body re-executed on resume (idempotent re-execution).
            assert body_executions == 2
            # The visitor-facing hook must NOT be re-created on replay: on_created
            # fires only once, and only one HOOK_CREATED event exists.
            assert on_created_calls == 1
            events = await storage.get_events(run_id)
            hook_created = [
                e
                for e in events
                if e.type == EventType.HOOK_CREATED and e.data.get("hook_id") == hook_id
            ]
            assert len(hook_created) == 1, "hook must not be re-created on replay"

            run = await storage.get_run(run_id)
            assert run.status == RunStatus.COMPLETED
            payload = deserialize_args(run.result)[0]
            assert payload["feedback"] == {"approved": True}
        finally:
            reset_config()

    @pytest.mark.asyncio
    async def test_fast_answer_from_on_created_completes(self):
        """A hook answered from within on_created (before the suspension bookkeeping
        exists) is not lost: the run completes on the local runtime."""
        from pyworkflow import configure, reset_config, start
        from pyworkflow.core.step import step
        from pyworkflow.core.workflow import workflow
        from pyworkflow.primitives.resume_hook import resume_hook
        from pyworkflow.primitives.step_hook import step_hook
        from pyworkflow.serialization.decoder import deserialize_args

        reset_config()

        @step(name="fast_answer_step")
        async def review_step():
            async def answer_immediately(token):
                # Deliver the answer synchronously, before the workflow has
                # finished recording its suspension.
                await resume_hook(token, {"approved": True, "fast": True}, storage=storage)

            feedback = await step_hook("fast_review", on_created=answer_immediately)
            return {"feedback": feedback}

        @workflow(name="fast_answer_workflow")
        async def review_workflow():
            return await review_step()

        try:
            storage = InMemoryStorageBackend()
            configure(storage=storage)
            run_id = await start(review_workflow, durable=True, storage=storage)

            run = await storage.get_run(run_id)
            assert run.status == RunStatus.COMPLETED, (
                f"fast-answered run should be COMPLETED, got {run.status}"
            )
            result = deserialize_args(run.result)[0]
            assert result == {"feedback": {"approved": True, "fast": True}}
        finally:
            reset_config()

    @pytest.mark.asyncio
    async def test_two_sequential_step_hooks_in_one_step_completes(self):
        """A step that suspends twice on the SAME step_id (two sequential
        step_hook rounds) completes — the second suspension must record its own
        STEP_SUSPENDED, not be deduped away by the first round's event."""
        from pyworkflow import configure, reset_config, start
        from pyworkflow.core.step import _generate_step_id, step
        from pyworkflow.core.workflow import workflow
        from pyworkflow.engine.events import EventType
        from pyworkflow.primitives.resume_hook import create_hook_token, resume_hook
        from pyworkflow.primitives.step_hook import step_hook
        from pyworkflow.serialization.decoder import deserialize_args

        reset_config()

        @step(name="two_round_step")
        async def review_step():
            first = await step_hook("round_one")
            second = await step_hook("round_two")
            return {"first": first, "second": second}

        @workflow(name="two_round_workflow")
        async def review_workflow():
            return await review_step()

        try:
            storage = InMemoryStorageBackend()
            configure(storage=storage)
            run_id = await start(review_workflow, durable=True, storage=storage)

            # Suspended on round one.
            assert (await storage.get_run(run_id)).status == RunStatus.SUSPENDED

            # Answer round one -> local runtime resumes -> suspends on round two.
            await resume_hook(
                create_hook_token(run_id, "step_hook_round_one_0"),
                {"n": 1},
                storage=storage,
            )
            assert (await storage.get_run(run_id)).status == RunStatus.SUSPENDED

            # Answer round two -> run completes.
            await resume_hook(
                create_hook_token(run_id, "step_hook_round_two_1"),
                {"n": 2},
                storage=storage,
            )
            run = await storage.get_run(run_id)
            assert run.status == RunStatus.COMPLETED, (
                f"two-round run should be COMPLETED, got {run.status}"
            )
            result = deserialize_args(run.result)[0]
            assert result == {"first": {"n": 1}, "second": {"n": 2}}

            # One STEP_SUSPENDED per suspended STEP_STARTED cycle for this step_id:
            # every start ended in a suspension except the final one that completed.
            events = await storage.get_events(run_id)
            step_id = _generate_step_id("two_round_step", (), {})
            started = [
                e
                for e in events
                if e.type == EventType.STEP_STARTED and e.data.get("step_id") == step_id
            ]
            suspended = [
                e
                for e in events
                if e.type == EventType.STEP_SUSPENDED and e.data.get("step_id") == step_id
            ]
            completed = [
                e
                for e in events
                if e.type == EventType.STEP_COMPLETED and e.data.get("step_id") == step_id
            ]
            assert len(completed) == 1
            assert len(suspended) == 2
            assert len(suspended) == len(started) - 1
        finally:
            reset_config()

    @pytest.mark.asyncio
    async def test_crash_replay_between_sequential_step_hooks_completes(self):
        """Crash-replay across the SECOND suspension: after the round-one answer
        is replayed by a fresh executor and the step re-suspends on round two,
        a fresh executor replays again and completes after the round-two answer."""
        from pyworkflow import configure, reset_config, resume, start
        from pyworkflow.core.step import step
        from pyworkflow.core.workflow import workflow
        from pyworkflow.engine.events import create_hook_received_event
        from pyworkflow.primitives.step_hook import step_hook
        from pyworkflow.serialization.encoder import serialize

        reset_config()

        @step(name="two_round_crash_step")
        async def review_step():
            first = await step_hook("r1")
            second = await step_hook("r2")
            return {"first": first, "second": second}

        @workflow(name="two_round_crash_workflow")
        async def review_workflow():
            return await review_step()

        try:
            storage = InMemoryStorageBackend()
            configure(storage=storage)
            run_id = await start(review_workflow, durable=True, storage=storage)
            assert (await storage.get_run(run_id)).status == RunStatus.SUSPENDED

            # Crash between rounds: record the round-one answer directly (no
            # auto-resume), then replay with a fresh executor.
            await storage.record_event(
                create_hook_received_event(
                    run_id=run_id, hook_id="step_hook_r1_0", payload=serialize({"n": 1})
                )
            )
            await resume(run_id, storage=storage)
            assert (await storage.get_run(run_id)).status == RunStatus.SUSPENDED

            # Crash again mid-second-suspension: record the round-two answer and
            # replay once more; the run must complete.
            await storage.record_event(
                create_hook_received_event(
                    run_id=run_id, hook_id="step_hook_r2_1", payload=serialize({"n": 2})
                )
            )
            result = await resume(run_id, storage=storage)
            assert result == {"first": {"n": 1}, "second": {"n": 2}}
            assert (await storage.get_run(run_id)).status == RunStatus.COMPLETED
        finally:
            reset_config()


class TestStepHookCounterAPI:
    """Tests for the public step-hook counter API used by cross-process restore."""

    @pytest.mark.asyncio
    async def test_counter_get_set_round_trip(self):
        """get_step_hook_counter/set_step_hook_counter round-trip through the context."""
        storage = InMemoryStorageBackend()
        ctx = LocalContext(
            run_id="counter_run", workflow_name="test_workflow", storage=storage, durable=True
        )
        assert ctx.get_step_hook_counter() == 0
        ctx.set_step_hook_counter(7)
        assert ctx.get_step_hook_counter() == 7
        # Backing storage stays the private attribute.
        assert ctx._step_hook_counter == 7

    @pytest.mark.asyncio
    async def test_restored_counter_reproduces_deterministic_hook_id(self):
        """A restored counter reproduces the same deterministic hook id on re-execution."""
        storage = InMemoryStorageBackend()
        run_id = "counter_run_2"
        await storage.create_run(
            WorkflowRun(run_id=run_id, workflow_name="test_workflow", status=RunStatus.RUNNING)
        )
        ctx = LocalContext(
            run_id=run_id, workflow_name="test_workflow", storage=storage, durable=True
        )
        ctx._is_step_worker = True

        # Simulate a checkpoint/restore across a process boundary: the app poked
        # the counter to 3 before re-executing the step.
        ctx.set_step_hook_counter(3)

        ctx_token = set_context(ctx)
        step_tokens = set_step_execution_context(f"{run_id}:step_test_abc123", storage)
        try:
            with pytest.raises(SuspensionSignal) as exc_info:
                await step_hook("resume_point")
            assert exc_info.value.data["hook_id"] == "step_hook_resume_point_3"
            # The counter advanced past the restored value.
            assert ctx.get_step_hook_counter() == 4
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
