"""
Standalone workflow module for the workflow-run-strategy end-to-end tests.

Imported by the worker subprocesses (via PYWORKFLOW_MODULE) and by the driver
script that starts runs / delivers hooks. Every step and workflow pass appends a
JSON line to ``$E2E_MARKER_DIR/<run_id>.jsonl`` recording *where* it executed:

- ``worker``: the ``E2E_WORKER_NAME`` env of the Celery worker process
- ``pid``: the OS pid of the process that ran the code
- ``is_step_worker``: whether the context was built by ``execute_step_task``

The test boots one worker on the workflow/schedule queues and a *separate* one
on the step queue, so a step's ``worker`` field proves whether it was dispatched
(step worker) or ran inline in the workflow task (workflow worker).
"""

import asyncio
import json
import os
from pathlib import Path

from pyworkflow import (
    FatalError,
    RetryableError,
    WorkflowRunStrategy,
    continue_as_new,
    hook,
    sleep,
    start_child_workflow,
    step,
    workflow,
)
from pyworkflow.context import get_context
from pyworkflow.primitives.step_hook import step_hook

ONE_THREAD = WorkflowRunStrategy.ONE_THREAD


def _marker_dir() -> Path:
    d = Path(os.environ["E2E_MARKER_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def _trace(event: str, **extra) -> None:
    ctx = get_context()
    record = {
        "event": event,
        "worker": os.environ.get("E2E_WORKER_NAME", "?"),
        "pid": os.getpid(),
        "is_step_worker": bool(getattr(ctx, "is_step_worker", False)),
        "strategy": ctx.workflow_run_strategy.value,
        **extra,
    }
    with open(_marker_dir() / f"{ctx.run_id}.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")


async def _write_token(token: str) -> None:
    run_id = token.split(":", 1)[0]
    (_marker_dir() / f"{run_id}.token").write_text(token)


# --------------------------------------------------------------------------- steps


@step()
async def add(x: int, y: int) -> int:
    _trace("step:add", x=x, y=y)
    return x + y


@step(force_local=True)
async def local_add(x: int, y: int) -> int:
    _trace("step:local_add", x=x, y=y)
    return x + y


@step(max_retries=3, retry_delay="1s")
async def flaky() -> int:
    """Fails twice (RetryableError), succeeds on the third attempt."""
    ctx = get_context()
    counter = _marker_dir() / f"{ctx.run_id}.attempts"
    attempts = int(counter.read_text()) if counter.exists() else 0
    attempts += 1
    counter.write_text(str(attempts))
    _trace("step:flaky", attempt=attempts)
    if attempts < 3:
        raise RetryableError(f"flaky attempt {attempts}")
    return attempts


@step()
async def boom() -> None:
    _trace("step:boom")
    raise FatalError("boom")


@step()
async def review() -> dict:
    _trace("step:review")
    feedback = await step_hook("review", on_created=_write_token)
    _trace("step:review:after_hook")
    return {"feedback": feedback}


@step()
async def slow(ms: int, i: int) -> int:
    """``i`` keeps every call a distinct step id (ids derive from args)."""
    await asyncio.sleep(ms / 1000)
    return ms


# ----------------------------------------------------------------------- workflows


@workflow(name="s_declared", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_declared(n: int = 3) -> int:
    _trace("wf:pass")
    total = 0
    for i in range(n):
        total = await add(total, i + 1)
    return total


@workflow(name="s_undeclared", durable=True)
async def s_undeclared(n: int = 3) -> int:
    _trace("wf:pass")
    total = 0
    for i in range(n):
        total = await add(total, i + 1)
    return total


@workflow(name="s_sleep", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_sleep() -> int:
    _trace("wf:pass")
    a = await add(1, 1)
    await sleep("2s")
    b = await add(a, 10)
    return b


@workflow(name="s_hook", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_hook() -> dict:
    _trace("wf:pass")
    a = await add(1, 1)
    payload = await hook("approval", on_created=_write_token)
    b = await add(a, 100)
    return {"a": a, "b": b, "payload": payload}


@workflow(name="s_retry", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_retry() -> int:
    _trace("wf:pass")
    return await flaky()


@workflow(name="s_fatal", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_fatal() -> None:
    _trace("wf:pass")
    await boom()


@workflow(name="s_gather", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_gather() -> list[int]:
    _trace("wf:pass")
    return list(await asyncio.gather(add(1, 1), add(2, 2), add(3, 3)))


@workflow(name="s_can", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_can(generation: int = 0) -> int:
    _trace("wf:pass", generation=generation)
    await add(generation, 1)
    if generation < 1:
        await continue_as_new(generation=generation + 1)
    return generation


@workflow(name="s_parent", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_parent() -> dict:
    _trace("wf:pass")
    a = await add(1, 1)
    child = await start_child_workflow(s_undeclared, n=2, wait_for_completion=True)
    b = await add(a, child)
    return {"a": a, "child": child, "b": b}


@workflow(name="s_child", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_child(n: int = 2) -> int:
    _trace("wf:pass")
    total = 0
    for i in range(n):
        total = await add(total, i + 1)
    return total


@workflow(name="s_parent_inline_child", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_parent_inline_child() -> dict:
    _trace("wf:pass")
    a = await add(1, 1)
    child = await start_child_workflow(s_child, n=2, wait_for_completion=True)
    b = await add(a, child)
    return {"a": a, "child": child, "b": b}


@workflow(name="s_step_hook", durable=True, workflow_run_strategy=ONE_THREAD)
async def s_step_hook() -> dict:
    _trace("wf:pass")
    return await review()


@workflow(name="s_force_local", durable=True)
async def s_force_local() -> int:
    _trace("wf:pass")
    a = await local_add(1, 1)
    b = await add(a, 2)
    return b


@workflow(name="s_many", durable=True)
async def s_many(n: int = 10) -> int:
    total = 0
    for i in range(n):
        total = await slow(5, i) + total
    return total
