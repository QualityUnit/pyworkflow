"""
Client-side driver for the workflow-run-strategy end-to-end tests.

Runs in its own process (like an API server would) with the same env as the
workers: it starts runs on the Celery runtime with an explicit
``workflow_run_strategy`` and delivers hook payloads. The CLI's ``workflows run``
has no strategy flag, so this stands in for the application code that calls
``pyworkflow.start(...)``.

Usage:
    driver start <workflow_name> <one_thread|distributed|none> [<kwargs_json>]
    driver hook <token> <payload_json>
"""

import asyncio
import json
import os
import sys

import pyworkflow
from pyworkflow import WorkflowRunStrategy
from pyworkflow.primitives.resume_hook import resume_hook
from pyworkflow.storage.file import FileStorageBackend

APP_MODULE = "_run_strategy_e2e_app"


def _storage() -> FileStorageBackend:
    return FileStorageBackend(base_path=os.environ["PYWORKFLOW_STORAGE_PATH"])


async def _start(workflow_name: str, strategy: str, kwargs: dict) -> str:
    storage = _storage()
    pyworkflow.configure(
        module=APP_MODULE,
        default_runtime="celery",
        default_durable=True,
        storage=storage,
    )
    meta = pyworkflow.get_workflow(workflow_name)
    if meta is None:
        raise SystemExit(f"unknown workflow {workflow_name!r}")
    strategy_value = None if strategy == "none" else WorkflowRunStrategy(strategy)
    return await pyworkflow.start(
        meta.func,
        runtime="celery",
        durable=True,
        storage=storage,
        workflow_run_strategy=strategy_value,
        **kwargs,
    )


async def _hook(token: str, payload) -> None:
    storage = _storage()
    pyworkflow.configure(
        module=APP_MODULE,
        default_runtime="celery",
        default_durable=True,
        storage=storage,
    )
    await resume_hook(token, payload, storage=storage)


def main(argv: list[str]) -> None:
    cmd = argv[1]
    if cmd == "start":
        kwargs = json.loads(argv[4]) if len(argv) > 4 else {}
        run_id = asyncio.run(_start(argv[2], argv[3], kwargs))
        print(f"RUN_ID={run_id}")
    elif cmd == "hook":
        asyncio.run(_hook(argv[2], json.loads(argv[3])))
        print("HOOK_OK")
    else:
        raise SystemExit(f"unknown command {cmd!r}")


if __name__ == "__main__":
    main(sys.argv)
