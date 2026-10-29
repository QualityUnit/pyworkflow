"""
Standalone workflow module for the SIGTERM-handoff end-to-end test (#733).

Imported by the worker subprocesses (via PYWORKFLOW_MODULE) and by the CLI that
starts the workflow. A parent starts a child; the child runs a quick step, then
a long "agent" step (``e2e_resume_child`` sleeps in between, so the agent step
runs inside a resume task) that blocks until a `release` marker file appears, so the
test can SIGTERM the worker while the agent step is running.

Everything the steps do is recorded under $E2E_MARKER_DIR, tagged with the
worker ($HOSTNAME) and pid, so the test can prove what ran where and when:
- executions.jsonl: one line per step execution start/finish
- tick-<worker>-<pid>: last heartbeat of a running agent step
- started: the agent step is running
- ready-<worker>: the worker is consuming (and its SIGTERM handler is installed)

E2E_INLINE=1 runs the steps inline in the child workflow task (force_local);
otherwise they are dispatched to step workers.
"""

import asyncio
import json
import os
import time
from pathlib import Path

from celery.signals import worker_ready

from pyworkflow import sleep, step, workflow
from pyworkflow.primitives.child_workflow import start_child_workflow

_INLINE = os.environ.get("E2E_INLINE", "1") == "1"


def _marker_dir() -> Path:
    d = Path(os.environ["E2E_MARKER_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def _worker() -> str:
    return os.environ.get("HOSTNAME", "?")


def _record(event: str) -> None:
    line = json.dumps({"t": time.time(), "event": event, "worker": _worker(), "pid": os.getpid()})
    with open(_marker_dir() / "executions.jsonl", "a") as f:
        f.write(line + "\n")


@worker_ready.connect
def _mark_ready(**_):
    (_marker_dir() / f"ready-{_worker()}").write_text("1")


@step(force_local=_INLINE)
async def prep_step() -> str:
    _record("prep")
    return "prepped"


@step(force_local=_INLINE, max_retries=0)
async def agent_step(prepped: str) -> str:
    d = _marker_dir()
    _record("agent_start")
    (d / "started").write_text("1")
    tick = d / f"tick-{_worker()}-{os.getpid()}"
    for _ in range(480):  # up to ~120s
        tick.write_text(str(time.time()))
        if (d / "release").exists():
            _record("agent_done")
            return f"{prepped}+agent"
        await asyncio.sleep(0.25)
    raise TimeoutError("release marker never appeared")


@workflow(durable=True)
async def e2e_child() -> str:
    return await agent_step(await prep_step())


@workflow(durable=True)
async def e2e_parent() -> str:
    return await start_child_workflow(e2e_child, wait_for_completion=True)


@workflow(durable=True)
async def e2e_resume_child() -> str:
    prepped = await prep_step()
    # The agent step then runs inside a resume_workflow task, not the start task.
    await sleep("1s")
    return await agent_step(prepped)


@workflow(durable=True)
async def e2e_resume_parent() -> str:
    return await start_child_workflow(e2e_resume_child, wait_for_completion=True)
