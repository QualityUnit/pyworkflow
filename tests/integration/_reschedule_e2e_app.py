"""
Standalone workflow module for the SIGTERM-reschedule end-to-end test.

Imported by the worker subprocess (via PYWORKFLOW_MODULE) and by the CLI that
starts the workflow. The single step blocks until a `release` marker file
appears, so the test can deterministically catch it mid-execution, SIGTERM the
worker, and prove a fresh worker re-runs it and the workflow completes.

Marker files live under $E2E_MARKER_DIR:
- writes `started` as soon as the step runs (so the test knows it's in-flight)
- waits for `release` before returning
"""

import asyncio
import os
from pathlib import Path

from pyworkflow import step, workflow


def _marker_dir() -> Path:
    return Path(os.environ["E2E_MARKER_DIR"])


@step(max_retries=1)
async def blocking_step() -> str:
    d = _marker_dir()
    d.mkdir(parents=True, exist_ok=True)
    # Signal that the step is executing (the test waits for this before SIGTERM).
    (d / "started").write_text("1")
    # Block until released, so the step is reliably in-flight when the worker dies.
    for _ in range(240):  # up to ~120s
        if (d / "release").exists():
            return "released"
        await asyncio.sleep(0.5)
    raise TimeoutError("release marker never appeared")


@workflow(durable=True)
async def e2e_blocking_workflow() -> str:
    return await blocking_step()
