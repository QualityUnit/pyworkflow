"""
End-to-end tests for inline ``step_hook()`` suspension against on-disk storage.

These complement the single-process, in-memory unit tests in
``tests/unit/test_step_hook.py`` by exercising the fix through a *real*
``FileStorageBackend`` and, crucially, resuming through **freshly constructed
backend instances** (with the config reset in between). That reproduces the
production shape of the bug: the workflow suspends in one process, the event log
is persisted to disk, and a *different* process replays it from that log.

Before the fix, a step that suspended via ``step_hook()`` on the inline (local
runtime / ``force_local``) path recorded no ``STEP_SUSPENDED`` event, so a fresh
replay saw the step's ``STEP_STARTED`` with no terminal event, treated it as
still in progress, and re-suspended forever -- the run was stranded.
"""

import pytest

from pyworkflow import configure, reset_config, resume, start
from pyworkflow.core.step import _generate_step_id, step
from pyworkflow.core.workflow import workflow
from pyworkflow.engine.events import (
    EventType,
    create_hook_received_event,
)
from pyworkflow.primitives.resume_hook import create_hook_token, resume_hook
from pyworkflow.primitives.step_hook import step_hook
from pyworkflow.serialization.decoder import deserialize_args
from pyworkflow.serialization.encoder import serialize
from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.schemas import RunStatus

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def reset_pyworkflow_config():
    """Reset configuration before and after each test."""
    reset_config()
    yield
    reset_config()


def _fresh_backend(storage_path) -> FileStorageBackend:
    """A brand-new FileStorageBackend over ``storage_path``.

    Constructing a new instance (rather than reusing the one that started the
    run) simulates a separate process: nothing is shared but the on-disk log.
    """
    return FileStorageBackend(base_path=str(storage_path))


async def _events(storage_path, run_id):
    return await _fresh_backend(storage_path).get_events(run_id)


async def _status(storage_path, run_id) -> RunStatus:
    run = await _fresh_backend(storage_path).get_run(run_id)
    return run.status


class TestInlineSuspensionFileStorage:
    """step_hook() suspend -> persist -> cross-backend resume, on real disk."""

    @pytest.mark.asyncio
    async def test_suspend_persists_step_suspended_and_resume_completes(self, tmp_path):
        """STEP_SUSPENDED is written to disk on suspend; a fresh backend resumes
        the run to completion instead of stranding it."""
        storage_path = tmp_path / "storage"

        @step(name="review_step")
        async def review_step():
            feedback = await step_hook("review")
            return {"feedback": feedback}

        @workflow(name="review_workflow")
        async def review_workflow():
            return await review_step()

        # --- "Process 1": start the workflow; it suspends on the hook. ---
        storage_start = _fresh_backend(storage_path)
        configure(storage=storage_start, default_durable=True)
        run_id = await start(review_workflow, durable=True, storage=storage_start)

        assert await _status(storage_path, run_id) == RunStatus.SUSPENDED

        # The STEP_SUSPENDED marker must be durably on disk, readable by any
        # process, so replay does not treat the step as still in progress.
        events = await _events(storage_path, run_id)
        suspended = [e for e in events if e.type == EventType.STEP_SUSPENDED]
        assert len(suspended) == 1, "STEP_SUSPENDED must be persisted on the inline path"
        assert suspended[0].data.get("step_id") == _generate_step_id("review_step", (), {})

        # --- "Process 2": fresh config + fresh backend deliver the answer. ---
        reset_config()
        storage_resume = _fresh_backend(storage_path)
        configure(storage=storage_resume, default_durable=True)

        token = create_hook_token(run_id, "step_hook_review_0")
        await resume_hook(token, {"approved": True}, storage=storage_resume)

        assert await _status(storage_path, run_id) == RunStatus.COMPLETED
        run = await _fresh_backend(storage_path).get_run(run_id)
        assert deserialize_args(run.result)[0] == {"feedback": {"approved": True}}

    @pytest.mark.asyncio
    async def test_crash_replay_resume_completes_without_duplicate_hook(self, tmp_path):
        """Simulated crash between hook delivery and resume: recording
        HOOK_RECEIVED and replaying from disk with a fresh executor completes the
        run and re-creates neither the hook nor a second STEP_SUSPENDED."""
        storage_path = tmp_path / "storage"

        @step(name="crash_step")
        async def crash_step():
            feedback = await step_hook("approval")
            return {"feedback": feedback}

        @workflow(name="crash_workflow")
        async def crash_workflow():
            return await crash_step()

        storage_start = _fresh_backend(storage_path)
        configure(storage=storage_start, default_durable=True)
        run_id = await start(crash_workflow, durable=True, storage=storage_start)
        assert await _status(storage_path, run_id) == RunStatus.SUSPENDED

        # Crash: the answer was recorded (HOOK_RECEIVED) but the process died
        # before resuming. Record it directly, then replay from a fresh backend.
        hook_id = "step_hook_approval_0"
        reset_config()
        storage_resume = _fresh_backend(storage_path)
        configure(storage=storage_resume, default_durable=True)
        await storage_resume.record_event(
            create_hook_received_event(
                run_id=run_id, hook_id=hook_id, payload=serialize({"approved": True})
            )
        )

        result = await resume(run_id, storage=storage_resume)
        assert result == {"feedback": {"approved": True}}
        assert await _status(storage_path, run_id) == RunStatus.COMPLETED

        # The visitor-facing hook must not be re-created on replay: exactly one
        # HOOK_CREATED in the durable log.
        events = await _events(storage_path, run_id)
        hook_created = [
            e
            for e in events
            if e.type == EventType.HOOK_CREATED and e.data.get("hook_id") == hook_id
        ]
        assert len(hook_created) == 1, "hook must not be re-created on replay"

    @pytest.mark.asyncio
    async def test_two_sequential_hooks_complete_across_fresh_backends(self, tmp_path):
        """A step suspending twice on the SAME step_id (two sequential rounds)
        completes when each round is answered through a fresh backend, and the
        durable log holds exactly one STEP_SUSPENDED per suspended start."""
        storage_path = tmp_path / "storage"

        @step(name="two_round_step")
        async def two_round_step():
            first = await step_hook("round_one")
            second = await step_hook("round_two")
            return {"first": first, "second": second}

        @workflow(name="two_round_workflow")
        async def two_round_workflow():
            return await two_round_step()

        storage_start = _fresh_backend(storage_path)
        configure(storage=storage_start, default_durable=True)
        run_id = await start(two_round_workflow, durable=True, storage=storage_start)
        assert await _status(storage_path, run_id) == RunStatus.SUSPENDED

        # Answer round one through a fresh backend -> re-suspends on round two.
        reset_config()
        storage_r1 = _fresh_backend(storage_path)
        configure(storage=storage_r1, default_durable=True)
        await resume_hook(
            create_hook_token(run_id, "step_hook_round_one_0"), {"n": 1}, storage=storage_r1
        )
        assert await _status(storage_path, run_id) == RunStatus.SUSPENDED

        # Answer round two through yet another fresh backend -> completes.
        reset_config()
        storage_r2 = _fresh_backend(storage_path)
        configure(storage=storage_r2, default_durable=True)
        await resume_hook(
            create_hook_token(run_id, "step_hook_round_two_1"), {"n": 2}, storage=storage_r2
        )

        assert await _status(storage_path, run_id) == RunStatus.COMPLETED
        run = await _fresh_backend(storage_path).get_run(run_id)
        assert deserialize_args(run.result)[0] == {"first": {"n": 1}, "second": {"n": 2}}

        # Exactly one STEP_SUSPENDED per suspended STEP_STARTED cycle: every start
        # for this step_id ended suspended except the final completing one.
        step_id = _generate_step_id("two_round_step", (), {})
        events = await _events(storage_path, run_id)
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

    @pytest.mark.asyncio
    async def test_fast_answer_from_on_created_completes(self, tmp_path):
        """A hook answered from within on_created (before the suspension is fully
        recorded) is not lost against on-disk storage: the run completes."""
        storage_path = tmp_path / "storage"
        storage_start = _fresh_backend(storage_path)

        @step(name="fast_step")
        async def fast_step():
            async def answer_immediately(token):
                await resume_hook(token, {"approved": True, "fast": True}, storage=storage_start)

            feedback = await step_hook("fast_review", on_created=answer_immediately)
            return {"feedback": feedback}

        @workflow(name="fast_workflow")
        async def fast_workflow():
            return await fast_step()

        configure(storage=storage_start, default_durable=True)
        run_id = await start(fast_workflow, durable=True, storage=storage_start)

        assert await _status(storage_path, run_id) == RunStatus.COMPLETED
        run = await _fresh_backend(storage_path).get_run(run_id)
        assert deserialize_args(run.result)[0] == {"feedback": {"approved": True, "fast": True}}

    @pytest.mark.asyncio
    async def test_repeated_replay_without_answer_stays_resumable(self, tmp_path):
        """Regression guard for the stranding bug: replaying a suspended run
        WITHOUT delivering the answer must keep it cleanly SUSPENDED (each replay
        re-suspends), and answering afterwards must still complete it."""
        storage_path = tmp_path / "storage"

        @step(name="patient_step")
        async def patient_step():
            feedback = await step_hook("patient")
            return {"feedback": feedback}

        @workflow(name="patient_workflow")
        async def patient_workflow():
            return await patient_step()

        storage_start = _fresh_backend(storage_path)
        configure(storage=storage_start, default_durable=True)
        run_id = await start(patient_workflow, durable=True, storage=storage_start)
        assert await _status(storage_path, run_id) == RunStatus.SUSPENDED

        # Replay several times with no answer available. Each fresh replay must
        # re-suspend cleanly (return None) rather than error or hang.
        for _ in range(3):
            reset_config()
            storage_replay = _fresh_backend(storage_path)
            configure(storage=storage_replay, default_durable=True)
            result = await resume(run_id, storage=storage_replay)
            assert result is None
            assert await _status(storage_path, run_id) == RunStatus.SUSPENDED

        # Now deliver the answer -> the run completes.
        reset_config()
        storage_answer = _fresh_backend(storage_path)
        configure(storage=storage_answer, default_durable=True)
        await resume_hook(
            create_hook_token(run_id, "step_hook_patient_0"), {"ok": True}, storage=storage_answer
        )
        assert await _status(storage_path, run_id) == RunStatus.COMPLETED
        run = await _fresh_backend(storage_path).get_run(run_id)
        assert deserialize_args(run.result)[0] == {"feedback": {"ok": True}}
