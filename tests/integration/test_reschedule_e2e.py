"""
End-to-end test for SIGTERM task rescheduling with REAL worker subprocesses.

Proves the production scenario: a prefork Celery worker is running a step when it
receives SIGTERM (spot reclaim); its ``worker_shutting_down`` handler re-enqueues
the in-flight step; a fresh worker picks it up and the workflow COMPLETES within
seconds -- instead of hanging until the broker visibility_timeout (~1h).

Sequence (deterministic):
1. Worker A runs the step, which blocks until a `release` marker appears.
2. SIGTERM A; wait until A *logs* the re-enqueue (its worker_shutting_down handler).
3. SIGKILL A's whole process group, so A cannot finish the step itself -- only a
   fresh worker can (mirrors k8s SIGKILL after the grace period).
4. Worker B starts, the step is released, and the workflow completes.

Requires Redis at localhost:6379. Uses a dedicated broker db (13) and a temp
FileStorageBackend shared across processes. Marked slow (boots real workers).
"""

import asyncio
import contextlib
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

try:
    import redis as _redis

    _redis.from_url("redis://localhost:6379/0").ping()
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not available"),
]

BROKER = "redis://localhost:6379/13"
APP_MODULE = "_reschedule_e2e_app"
WORKFLOW = "e2e_blocking_workflow"
RESCHEDULE_LOG = "re-enqueued in-flight task on shutdown"
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_RUN_ID_RE = re.compile(r"run_[0-9a-f]{16}")


def _base_env(storage_path: str, marker_dir: str) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "PYWORKFLOW_CELERY_BROKER": BROKER,
            "PYWORKFLOW_CELERY_RESULT_BACKEND": BROKER,
            "PYWORKFLOW_RUNTIME": "celery",
            "PYWORKFLOW_STORAGE_TYPE": "file",
            "PYWORKFLOW_STORAGE_PATH": storage_path,
            "PYWORKFLOW_MODULE": APP_MODULE,
            "E2E_MARKER_DIR": marker_dir,
            "PYWORKFLOW_RESCHEDULE_ON_SIGTERM": "1",
            "PYTHONPATH": _APP_DIR + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )
    return env


def _spawn_worker(env: dict, hostname: str, logfile) -> subprocess.Popen:
    # start_new_session so we can signal the whole group (main + prefork children).
    return subprocess.Popen(
        [
            sys.executable, "-m", "pyworkflow.cli",
            "--module", APP_MODULE,
            "worker", "run", "--loglevel", "warning",
        ],
        env={**env, "HOSTNAME": hostname},
        stdout=logfile,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _killpg(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(Exception):
            proc.wait(timeout=10)


def _run_status(storage_path: str, run_id: str) -> str:
    from pyworkflow.storage.file import FileStorageBackend

    storage = FileStorageBackend(base_path=storage_path)

    async def _get():
        run = await storage.get_run(run_id)
        return run.status.value if run else "NONE"

    return asyncio.run(_get())


def _wait_for(predicate, timeout: float, interval: float = 0.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_sigterm_reschedule_resumes_workflow(tmp_path):
    storage_path = str(tmp_path / "storage")
    marker_dir = tmp_path / "markers"
    marker_dir.mkdir()
    env = _base_env(storage_path, str(marker_dir))
    log_a = tmp_path / "worker_a.log"
    log_b = tmp_path / "worker_b.log"

    raw = _redis.from_url(BROKER, decode_responses=True)
    raw.flushdb()

    worker_a = worker_b = None
    with open(log_a, "w") as fa, open(log_b, "w") as fb:
        try:
            # 1. Worker A (prefork) -- will run the step, then we SIGTERM it.
            worker_a = _spawn_worker(env, "e2e-pod-a", fa)

            # 2. Start the workflow (separate CLI process, same broker/storage).
            started = subprocess.run(
                [
                    sys.executable, "-m", "pyworkflow.cli",
                    "--module", APP_MODULE,
                    "workflows", "run", WORKFLOW, "--no-wait",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            m = _RUN_ID_RE.search(started.stdout + started.stderr)
            if m:
                run_id = m.group(0)
            else:
                runs = list((Path(storage_path) / "runs").glob("run_*.json"))
                assert runs, f"no run created:\n{started.stdout}\n{started.stderr}"
                run_id = runs[0].stem

            # 3. Wait until the step is actually executing on worker A.
            assert _wait_for(lambda: (marker_dir / "started").exists(), timeout=60), (
                f"step never started on worker A\n{log_a.read_text()}"
            )

            # 4. SIGTERM A and wait until it LOGS the re-enqueue (handler fired).
            worker_a.send_signal(signal.SIGTERM)
            assert _wait_for(
                lambda: RESCHEDULE_LOG in log_a.read_text(), timeout=30
            ), f"worker A never logged a reschedule on SIGTERM\n{log_a.read_text()}"

            # 5. Hard-kill A's whole group so it cannot complete the step itself;
            #    only the re-enqueued copy on a fresh worker can finish it.
            _killpg(worker_a)

            # 6. Fresh worker B picks up the re-enqueued step.
            worker_b = _spawn_worker(env, "e2e-pod-b", fb)

            # 7. Release the (re-run) step so the workflow can finish.
            (marker_dir / "release").write_text("go")

            # 8. Must COMPLETE within seconds (visibility_timeout is 3600s, so a
            #    completion now proves the reschedule -- not broker redelivery).
            _wait_for(
                lambda: _run_status(storage_path, run_id) in ("completed", "failed"),
                timeout=90,
            )
            final = _run_status(storage_path, run_id)
            assert final == "completed", (
                f"run {run_id} ended {final!r}, expected completed\n"
                f"--- A ---\n{log_a.read_text()}\n--- B ---\n{log_b.read_text()}"
            )
        finally:
            _killpg(worker_a)
            _killpg(worker_b)
            raw.flushdb()
