"""
Recovering a workflow task whose delivery died mid-execution (#733).

With the SIGTERM handoff, a task still running at the end of the soft shutdown
is terminated and its message redelivered. The redelivery must pick the run up
from its event log: re-run the inline step it died in, not re-run steps that
already completed, and not wait forever for the interrupted step.
"""

import pytest

from pyworkflow import step, workflow
from pyworkflow.celery import tasks as celery_tasks
from pyworkflow.core.registry import get_workflow
from pyworkflow.engine.events import (
    EventType,
    create_step_started_event,
    create_workflow_suspended_event,
)
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


class _WorkerKilled(BaseException):
    """Stands in for the worker process dying mid-step (not caught as a failure)."""


def _make_workflow(name: str, executions: list[str], kill: dict[str, bool]):
    @step(name=f"{name}_prep", force_local=True)
    async def prep() -> str:
        executions.append("prep")
        return "prepped"

    @step(name=f"{name}_agent", force_local=True)
    async def agent(prepped: str) -> str:
        executions.append("agent")
        if kill["agent"]:
            raise _WorkerKilled()
        return f"{prepped}+agent"

    @workflow(name=name)
    async def wf() -> str:
        return await agent(await prep())

    return wf


def _started(step_id: str):
    return create_step_started_event(
        run_id="r", step_id=step_id, step_name=step_id, args="[]", kwargs="{}", attempt=1
    )


def test_forget_interrupted_inline_steps_keeps_dispatched_steps():
    dispatched, inline = _started("step_dispatched"), _started("step_inline")
    suspended = create_workflow_suspended_event(
        run_id="r", reason="step_dispatch:step_dispatched", step_id="step_dispatched"
    )

    kept = celery_tasks._forget_interrupted_inline_steps([dispatched, suspended, inline])

    assert kept == [dispatched, suspended]


@pytest.mark.asyncio
async def test_start_redelivery_reruns_the_interrupted_inline_step():
    executions: list[str] = []
    kill = {"agent": True}
    _make_workflow("ir_start", executions, kill)
    storage = InMemoryStorageBackend()

    async def deliver():
        return await celery_tasks._start_workflow_on_worker(
            workflow_meta=get_workflow("ir_start"),
            args=(),
            kwargs={},
            storage=storage,
            run_id="run_ir_start",
        )

    with pytest.raises(_WorkerKilled):
        await deliver()
    assert (await storage.get_run("run_ir_start")).status == RunStatus.RUNNING

    kill["agent"] = False
    await deliver()

    # Before: replay saw the agent step "in progress" and suspended forever.
    run = await storage.get_run("run_ir_start")
    assert run.status == RunStatus.COMPLETED
    assert executions == ["prep", "agent", "agent"]


@pytest.mark.asyncio
async def test_resume_redelivery_recovers_a_running_run():
    executions: list[str] = []
    kill = {"agent": True}
    _make_workflow("ir_resume", executions, kill)
    storage = InMemoryStorageBackend()
    await storage.create_run(
        WorkflowRun(
            run_id="run_ir_resume",
            workflow_name="ir_resume",
            status=RunStatus.SUSPENDED,
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
    )

    with pytest.raises(_WorkerKilled):
        await celery_tasks._resume_workflow_on_worker("run_ir_resume", storage)
    assert (await storage.get_run("run_ir_resume")).status == RunStatus.RUNNING
    kill["agent"] = False

    # A second resume task (not a redelivery) is a duplicate: skip it.
    assert await celery_tasks._resume_workflow_on_worker("run_ir_resume", storage) is None
    assert executions == ["prep", "agent"]

    # The redelivered message recovers the run.
    result = await celery_tasks._resume_workflow_on_worker(
        "run_ir_resume", storage, redelivered=True
    )

    assert result == "prepped+agent"
    run = await storage.get_run("run_ir_resume")
    assert run.status == RunStatus.COMPLETED
    assert run.recovery_attempts == 1
    assert executions == ["prep", "agent", "agent"]
    interrupted = await storage.get_events(
        "run_ir_resume", event_types=[EventType.WORKFLOW_INTERRUPTED.value]
    )
    assert len(interrupted) == 1


@pytest.mark.asyncio
async def test_resume_redelivery_of_a_suspended_run_is_a_normal_resume():
    executions: list[str] = []
    _make_workflow("ir_resume_ok", executions, {"agent": False})
    storage = InMemoryStorageBackend()
    await storage.create_run(
        WorkflowRun(
            run_id="run_ir_resume_ok",
            workflow_name="ir_resume_ok",
            status=RunStatus.SUSPENDED,
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(),
        )
    )

    result = await celery_tasks._resume_workflow_on_worker(
        "run_ir_resume_ok", storage, redelivered=True
    )

    assert result == "prepped+agent"
    assert (await storage.get_run("run_ir_resume_ok")).recovery_attempts == 0
