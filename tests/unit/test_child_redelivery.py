"""
``start_child_workflow_task`` can be delivered more than once (SIGTERM handoff,
broker redelivery). Each delivery must continue the child from where it is, not
run it from scratch (#733).
"""

from unittest.mock import AsyncMock, patch

import pytest

from pyworkflow import step, workflow
from pyworkflow.celery import tasks as celery_tasks
from pyworkflow.engine.events import (
    EventType,
    create_child_workflow_completed_event,
    create_child_workflow_started_event,
    create_workflow_completed_event,
)
from pyworkflow.serialization.encoder import serialize, serialize_args, serialize_kwargs
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun

PARENT = "run_redeliver_parent"
CHILD = "run_redeliver_child"
CHILD_ID = "child_redeliver"


async def _storage_with_child(status: RunStatus, **run_fields) -> InMemoryStorageBackend:
    storage = InMemoryStorageBackend()
    await storage.create_run(
        WorkflowRun(
            run_id=PARENT,
            workflow_name="redeliver_parent",
            status=RunStatus.SUSPENDED,
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
    )
    await storage.record_event(
        create_child_workflow_started_event(
            run_id=PARENT,
            child_id=CHILD_ID,
            child_run_id=CHILD,
            child_workflow_name="redeliver_child",
            args=serialize_args(),
            kwargs=serialize_kwargs(),
            wait_for_completion=True,
        )
    )
    await storage.create_run(
        WorkflowRun(
            run_id=CHILD,
            workflow_name="redeliver_child",
            status=status,
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
            parent_run_id=PARENT,
            **run_fields,
        )
    )
    return storage


async def _parent_events(storage, event_type: EventType) -> list:
    return await storage.get_events(PARENT, event_types=[event_type.value])


class TestClaimChildRun:
    @pytest.mark.asyncio
    async def test_pending_is_claimed_for_a_fresh_start(self):
        storage = await _storage_with_child(RunStatus.PENDING)

        assert await celery_tasks._claim_child_run(CHILD, storage, None) == []
        assert (await storage.get_run(CHILD)).status == RunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_pending_lost_claim_is_skipped(self):
        # Another delivery claimed the run between our read and the CAS.
        storage = await _storage_with_child(RunStatus.PENDING)

        with patch.object(storage, "try_claim_run", new=AsyncMock(return_value=False)):
            assert await celery_tasks._claim_child_run(CHILD, storage, None) is None

    @pytest.mark.asyncio
    async def test_running_is_recovered_from_the_event_log(self):
        storage = await _storage_with_child(RunStatus.RUNNING)

        events = await celery_tasks._claim_child_run(CHILD, storage, None)

        assert events is not None
        assert [e.type for e in events] == [EventType.WORKFLOW_INTERRUPTED]
        run = await storage.get_run(CHILD)
        assert run.status == RunStatus.RUNNING
        assert run.recovery_attempts == 1

    @pytest.mark.asyncio
    async def test_exhausted_recovery_fails_child_and_notifies_parent(self):
        storage = await _storage_with_child(
            RunStatus.RUNNING, recovery_attempts=3, max_recovery_attempts=3
        )

        with patch.object(
            celery_tasks, "_trigger_parent_resumption_celery", new=AsyncMock()
        ) as trigger:
            assert await celery_tasks._claim_child_run(CHILD, storage, None) is None

        assert (await storage.get_run(CHILD)).status == RunStatus.FAILED
        failed = await _parent_events(storage, EventType.CHILD_WORKFLOW_FAILED)
        assert len(failed) == 1
        assert failed[0].data["child_run_id"] == CHILD
        trigger.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_completed_child_notifies_parent_if_it_was_missed(self):
        storage = await _storage_with_child(RunStatus.COMPLETED)
        # The resume path stores run.result as serialize_args(result); the
        # parent must still get serialize(result), taken from the child's log.
        await storage.update_run_status(CHILD, RunStatus.COMPLETED, result=serialize_args(42))
        await storage.record_event(
            create_workflow_completed_event(CHILD, serialize(42), "redeliver_child")
        )

        with patch.object(
            celery_tasks, "_trigger_parent_resumption_celery", new=AsyncMock()
        ) as trigger:
            assert await celery_tasks._claim_child_run(CHILD, storage, None) is None

        completed = await _parent_events(storage, EventType.CHILD_WORKFLOW_COMPLETED)
        assert [e.data["result"] for e in completed] == [serialize(42)]
        trigger.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_completed_child_already_notified_is_a_noop(self):
        storage = await _storage_with_child(RunStatus.COMPLETED)
        await storage.record_event(
            create_child_workflow_completed_event(
                run_id=PARENT, child_id=CHILD_ID, child_run_id=CHILD, result=serialize(42)
            )
        )

        with patch.object(
            celery_tasks, "_trigger_parent_resumption_celery", new=AsyncMock()
        ) as trigger:
            assert await celery_tasks._claim_child_run(CHILD, storage, None) is None

        assert len(await _parent_events(storage, EventType.CHILD_WORKFLOW_COMPLETED)) == 1
        trigger.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_suspended_child_is_left_to_the_resume_path(self):
        storage = await _storage_with_child(RunStatus.SUSPENDED)

        assert await celery_tasks._claim_child_run(CHILD, storage, None) is None
        assert (await storage.get_run(CHILD)).status == RunStatus.SUSPENDED
        assert await storage.get_events(CHILD) == []

    @pytest.mark.asyncio
    async def test_missing_run_is_skipped(self):
        assert await celery_tasks._claim_child_run(CHILD, InMemoryStorageBackend(), None) is None


class _WorkerKilled(BaseException):
    """Stands in for the worker process dying mid-step (not caught as a failure)."""


@pytest.mark.asyncio
async def test_redelivered_child_does_not_rerun_completed_steps():
    executions: list[str] = []
    kill_in_agent = True

    @step(name="redeliver_prep", force_local=True)
    async def prep() -> str:
        executions.append("prep")
        return "prepped"

    @step(name="redeliver_agent", force_local=True)
    async def agent(prepped: str) -> str:
        executions.append("agent")
        if kill_in_agent:
            raise _WorkerKilled()
        return f"{prepped}+agent"

    @workflow(name="redeliver_child")
    async def child_wf() -> str:
        return await agent(await prep())

    storage = await _storage_with_child(RunStatus.PENDING)

    async def deliver() -> None:
        await celery_tasks._execute_child_workflow_on_worker(
            workflow_func=child_wf,
            workflow_name="redeliver_child",
            args=(),
            kwargs={},
            child_run_id=CHILD,
            storage=storage,
            storage_config=None,
            parent_run_id=PARENT,
            child_id=CHILD_ID,
            wait_for_completion=False,
        )

    # First delivery dies inside the agent step, after prep completed.
    with pytest.raises(_WorkerKilled):
        await deliver()
    assert executions == ["prep", "agent"]
    assert (await storage.get_run(CHILD)).status == RunStatus.RUNNING

    # The redelivered task replays prep instead of running it again.
    kill_in_agent = False
    await deliver()

    assert executions == ["prep", "agent", "agent"]
    child = await storage.get_run(CHILD)
    assert child.status == RunStatus.COMPLETED
    completed = await _parent_events(storage, EventType.CHILD_WORKFLOW_COMPLETED)
    assert [e.data["result"] for e in completed] == [serialize("prepped+agent")]

    # A third, late delivery of the same message does nothing.
    await deliver()
    assert executions == ["prep", "agent", "agent"]
    assert len(await _parent_events(storage, EventType.CHILD_WORKFLOW_COMPLETED)) == 1
