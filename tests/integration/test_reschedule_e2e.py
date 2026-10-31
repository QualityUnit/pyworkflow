"""
End-to-end test for the SIGTERM handoff with REAL worker subprocesses (#733).

Production scenario: a prefork worker is running a child workflow's long step
when it receives SIGTERM (deploy, scale-down, spot reclaim). The step must run
on exactly one worker at a time:

- If the step finishes within the soft shutdown timeout, it runs once, on the
  worker that received SIGTERM, and is not handed off.
- Otherwise the worker terminates it at the end of the timeout and the broker
  redelivers it once. A live worker continues the child from its event log:
  completed steps are not re-run, and the interrupted step starts again only
  after the original is dead.

Before the fix, the original kept running through warm shutdown while two
copies started on other workers (a re-published one and the original message
restored by kombu), so the step ran three times concurrently.

The worker that receives SIGTERM is never SIGKILLed here: it must exit on its
own. Requires Redis (PYWORKFLOW_E2E_REDIS, default redis://localhost:6379); uses
broker db 13 and a temp FileStorageBackend shared across processes. Marked slow
(boots real workers).
"""

import asyncio
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REDIS = os.environ.get("PYWORKFLOW_E2E_REDIS", "redis://localhost:6379").rstrip("/")

try:
    import redis as _redis

    _redis.from_url(f"{REDIS}/0").ping()
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not available"),
]

BROKER = f"{REDIS}/13"
APP_MODULE = "_reschedule_e2e_app"
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_RUN_ID_RE = re.compile(r"run_[0-9a-f]{16}")


def _wait_for(predicate, timeout: float, interval: float = 0.25) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class _Cluster:
    """Worker subprocesses sharing one broker, one file storage and one marker dir."""

    def __init__(self, tmp_path: Path, *, inline: bool, soft_shutdown_timeout: float):
        self.tmp_path = tmp_path
        self.storage_path = str(tmp_path / "storage")
        self.markers = tmp_path / "markers"
        self.markers.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            {
                "PYWORKFLOW_CELERY_BROKER": BROKER,
                "PYWORKFLOW_CELERY_RESULT_BACKEND": BROKER,
                "PYWORKFLOW_RUNTIME": "celery",
                "PYWORKFLOW_STORAGE_TYPE": "file",
                "PYWORKFLOW_STORAGE_PATH": self.storage_path,
                "PYWORKFLOW_MODULE": APP_MODULE,
                "PYWORKFLOW_RESCHEDULE_ON_SIGTERM": "1",
                "PYWORKFLOW_SOFT_SHUTDOWN_TIMEOUT": str(soft_shutdown_timeout),
                "E2E_MARKER_DIR": str(self.markers),
                "E2E_INLINE": "1" if inline else "0",
                "PYTHONPATH": _APP_DIR + os.pathsep + os.environ.get("PYTHONPATH", ""),
            }
        )
        self.env.pop("REMAP_SIGTERM", None)  # exercise pyworkflow's own handler
        self.workers: dict[str, subprocess.Popen] = {}
        self._logs: list = []

    def spawn(self, name: str) -> subprocess.Popen:
        log = open(self.tmp_path / f"worker_{name}.log", "w")  # noqa: SIM115
        self._logs.append(log)
        # start_new_session so cleanup can signal the whole group (main + children).
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pyworkflow.cli",
                "--module",
                APP_MODULE,
                "worker",
                "run",
                "--loglevel",
                "info",
                "--hostname",
                f"{name}@e2e",
                "--",
                "--concurrency=2",
            ],
            env={**self.env, "HOSTNAME": name},
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.workers[name] = proc
        assert _wait_for(lambda: (self.markers / f"ready-{name}").exists(), 60), (
            f"worker {name} never became ready\n{self.logs()}"
        )
        return proc

    def start_parent(self, workflow_name: str = "e2e_parent") -> str:
        started = subprocess.run(
            [
                sys.executable,
                "-m",
                "pyworkflow.cli",
                "--module",
                APP_MODULE,
                "workflows",
                "run",
                workflow_name,
                "--no-wait",
            ],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        m = _RUN_ID_RE.search(started.stdout + started.stderr)
        assert m, f"no run id:\n{started.stdout}\n{started.stderr}"
        return m.group(0)

    def run_status(self, run_id: str) -> str:
        from pyworkflow.storage.file import FileStorageBackend

        async def _get():
            run = await FileStorageBackend(base_path=self.storage_path).get_run(run_id)
            return run.status.value if run else "NONE"

        return asyncio.run(_get())

    def executions(self, event: str) -> list[dict]:
        path = self.markers / "executions.jsonl"
        if not path.exists():
            return []
        records = [json.loads(line) for line in path.read_text().splitlines()]
        return [r for r in records if r["event"] == event]

    def last_tick(self, worker: str) -> float:
        ticks = [float(p.read_text()) for p in self.markers.glob(f"tick-{worker}-*")]
        assert ticks, f"no heartbeat from worker {worker}"
        return max(ticks)

    def logs(self) -> str:
        return "\n".join(
            f"--- {p.name} ---\n{p.read_text()}" for p in sorted(self.tmp_path.glob("worker_*.log"))
        )

    def close(self) -> None:
        for proc in self.workers.values():
            if proc.poll() is None:
                with contextlib.suppress(Exception):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=10)
        for log in self._logs:
            log.close()


@pytest.fixture
def cluster_factory(tmp_path):
    raw = _redis.from_url(BROKER)
    raw.flushdb()
    clusters: list[_Cluster] = []

    def make(**kwargs) -> _Cluster:
        cluster = _Cluster(tmp_path, **kwargs)
        clusters.append(cluster)
        return cluster

    yield make
    for cluster in clusters:
        cluster.close()
    raw.flushdb()


def test_sigterm_hands_off_an_inflight_child_exactly_once(cluster_factory):
    """The step outlasts the soft timeout: terminated, then redelivered once."""
    c = cluster_factory(inline=True, soft_shutdown_timeout=2)
    worker_a = c.spawn("A")
    run_id = c.start_parent()
    assert _wait_for(lambda: (c.markers / "started").exists(), 60), c.logs()
    c.spawn("B")

    worker_a.send_signal(signal.SIGTERM)
    # A shuts itself down: wait 2s, terminate the step, exit. No SIGKILL.
    assert worker_a.wait(timeout=60) is not None
    (c.markers / "release").write_text("go")

    assert _wait_for(lambda: c.run_status(run_id) in ("completed", "failed"), 90), c.logs()
    assert c.run_status(run_id) == "completed", c.logs()

    # The completed prep step is replayed, not re-run.
    assert [r["worker"] for r in c.executions("prep")] == ["A"], c.logs()
    # The interrupted agent step ran again once, on B, after A's copy was dead.
    starts = c.executions("agent_start")
    assert [r["worker"] for r in starts] == ["A", "B"], c.logs()
    assert [r["worker"] for r in c.executions("agent_done")] == ["B"], c.logs()
    assert c.last_tick("A") < starts[1]["t"], "the copy started while A was still running"


def test_sigterm_lets_a_step_finish_within_the_soft_timeout(cluster_factory):
    """The step finishes inside the soft timeout: it runs once and is not handed off."""
    c = cluster_factory(inline=False, soft_shutdown_timeout=10)
    worker_a = c.spawn("A")
    run_id = c.start_parent()
    assert _wait_for(lambda: (c.markers / "started").exists(), 60), c.logs()
    c.spawn("B")

    worker_a.send_signal(signal.SIGTERM)
    time.sleep(1)
    (c.markers / "release").write_text("go")
    assert worker_a.wait(timeout=60) is not None

    assert _wait_for(lambda: c.run_status(run_id) in ("completed", "failed"), 90), c.logs()
    assert c.run_status(run_id) == "completed", c.logs()
    assert [r["worker"] for r in c.executions("agent_start")] == ["A"], c.logs()
    assert [r["worker"] for r in c.executions("agent_done")] == ["A"], c.logs()


def test_sigterm_hands_off_a_step_running_inside_a_resume_task(cluster_factory):
    """
    The killed task is a resume_workflow task: its redelivery must recover the
    RUNNING child instead of skipping it as a duplicate resume.
    """
    c = cluster_factory(inline=True, soft_shutdown_timeout=2)
    worker_a = c.spawn("A")
    run_id = c.start_parent("e2e_resume_parent")
    assert _wait_for(lambda: (c.markers / "started").exists(), 60), c.logs()
    c.spawn("B")

    worker_a.send_signal(signal.SIGTERM)
    assert worker_a.wait(timeout=60) is not None
    (c.markers / "release").write_text("go")

    assert _wait_for(lambda: c.run_status(run_id) in ("completed", "failed"), 90), c.logs()
    assert c.run_status(run_id) == "completed", c.logs()
    assert "Resume redelivered for a RUNNING workflow, recovering" in c.logs()
    assert [r["worker"] for r in c.executions("prep")] == ["A"], c.logs()
    starts = c.executions("agent_start")
    assert [r["worker"] for r in starts] == ["A", "B"], c.logs()
    assert [r["worker"] for r in c.executions("agent_done")] == ["B"], c.logs()
    assert c.last_tick("A") < starts[1]["t"], "the copy started while A was still running"
