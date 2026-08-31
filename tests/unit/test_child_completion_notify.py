"""
A child workflow that completes on the *resume* path must hand its parent the
bare result, exactly like a child that completes on the fresh-start path.

Regression: ``_resume_workflow_on_worker`` notified the parent with
``serialize_args(result)`` while ``_execute_child_workflow_on_worker`` used
``serialize(result)``. The parent replays ``CHILD_WORKFLOW_COMPLETED`` with
``deserialize()``, so a child that suspended even once (a dispatched step, a
sleep, a hook) resolved to ``[result]`` in the parent instead of ``result``.
"""

from unittest.mock import AsyncMock, patch

import pytest

from pyworkflow import workflow
from pyworkflow.celery import tasks as celery_tasks
from pyworkflow.engine.events import create_workflow_started_event
from pyworkflow.serialization.decoder import deserialize
from pyworkflow.serialization.encoder import serialize_args, serialize_kwargs
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


@pytest.mark.asyncio
async def test_child_completing_on_resume_hands_parent_the_bare_result():
    @workflow(name="ccn_child")
    async def child_wf(n: int) -> int:
        return n + 1

    storage = InMemoryStorageBackend()
    await storage.create_run(
        WorkflowRun(
            run_id="run_ccn_child",
            workflow_name="ccn_child",
            status=RunStatus.SUSPENDED,
            input_args=serialize_args(),
            input_kwargs=serialize_kwargs(n=2),
            parent_run_id="run_ccn_parent",
        )
    )
    await storage.record_event(
        create_workflow_started_event(
            run_id="run_ccn_child",
            workflow_name="ccn_child",
            args=serialize_args(),
            kwargs=serialize_kwargs(n=2),
        )
    )

    with patch.object(
        celery_tasks, "_notify_parent_of_child_completion", new=AsyncMock()
    ) as notify:
        result = await celery_tasks._resume_workflow_on_worker(
            run_id="run_ccn_child", storage=storage
        )

    assert result == 3
    notify.assert_awaited_once()
    kwargs = notify.await_args.kwargs
    assert kwargs["run"].parent_run_id == "run_ccn_parent"
    assert kwargs["status"] == RunStatus.COMPLETED
    # What the parent will see after replaying CHILD_WORKFLOW_COMPLETED.
    assert deserialize(kwargs["result"]) == 3
