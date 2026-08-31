"""
End-to-end tests for ``WorkflowRunStrategy`` against REAL Celery workers.

Topology (all sharing one Redis broker db and one on-disk FileStorageBackend):

- ``wf-worker``   consumes ``pyworkflow.workflows`` + ``pyworkflow.schedules``
- ``step-worker`` consumes ``pyworkflow.steps`` only
- a driver subprocess (stand-in for the application) starts runs and delivers hooks

Every step records which worker it ran on (``$E2E_MARKER_DIR/<run_id>.jsonl``),
so the tests can prove the strategy end to end:

- ``DISTRIBUTED``: regular steps execute on ``step-worker`` (dispatched)
- ``ONE_THREAD``:  every step executes on ``wf-worker`` inside the workflow task,
  the journal carries no ``STEP_STARTED`` / ``step_dispatch`` suspension, and the
  run still survives sleep / hook / retry / child suspensions
  without re-executing steps that already completed.

Requires Redis at localhost:6379 (uses db 14). Marked slow (boots real workers).
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
from dataclasses import dataclass
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

BROKER = "redis://localhost:6379/14"
APP_MODULE = "_run_strategy_e2e_app"
DRIVER = "_run_strategy_e2e_driver"
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_RUN_ID_RE = re.compile(r"RUN_ID=(\S+)")

WF_WORKER = "wf-worker"
STEP_WORKER = "step-worker"


# ----------------------------------------------------------------------- helpers


def _wait_for(predicate, timeout: float, interval: float = 0.25) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _killpg(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        with contextlib.suppress(Exception):
            proc.wait(timeout=15)
        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


@dataclass
class Cluster:
    storage_path: str
    marker_dir: Path
    env: dict
    logs: dict[str, Path]

    # -- storage reads (fresh backend each time: nothing shared with the workers)

    def _backend(self):
        from pyworkflow.storage.file import FileStorageBackend

        return FileStorageBackend(base_path=self.storage_path)

    def run(self, run_id: str):
        return asyncio.run(self._backend().get_run(run_id))

    def status(self, run_id: str) -> str:
        run = self.run(run_id)
        return run.status.value if run else "NONE"

    def result(self, run_id: str):
        from pyworkflow.serialization.decoder import deserialize_args

        run = self.run(run_id)
        return deserialize_args(run.result)[0] if run and run.result else None

    def events(self, run_id: str) -> list:
        return asyncio.run(self._backend().get_events(run_id))

    def event_types(self, run_id: str) -> list[str]:
        return [e.type.value.replace(".", "_") for e in self.events(run_id)]

    def list_runs(self) -> list:
        runs, _cursor = asyncio.run(self._backend().list_runs(limit=1000))
        return runs

    def wait_status(self, run_id: str, *statuses: str, timeout: float = 60) -> str:
        _wait_for(lambda: self.status(run_id) in statuses, timeout=timeout)
        return self.status(run_id)

    def wait_terminal(self, run_id: str, timeout: float = 60) -> str:
        return self.wait_status(
            run_id, "completed", "failed", "cancelled", "continued_as_new", timeout=timeout
        )

    # -- trace written by the app module

    def trace(self, run_id: str) -> list[dict]:
        path = self.marker_dir / f"{run_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def steps(self, run_id: str) -> list[dict]:
        return [t for t in self.trace(run_id) if t["event"].startswith("step:")]

    def token(self, run_id: str, timeout: float = 30) -> str:
        path = self.marker_dir / f"{run_id}.token"
        assert _wait_for(path.exists, timeout=timeout), f"hook token never written for {run_id}"
        return path.read_text()

    # -- driver (application-side) actions

    def _driver(self, *args: str) -> str:
        proc = subprocess.run(
            [sys.executable, "-m", DRIVER, *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, f"driver failed:\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout + proc.stderr

    def start(self, workflow_name: str, strategy: str = "none", **kwargs) -> str:
        out = self._driver("start", workflow_name, strategy, json.dumps(kwargs))
        m = _RUN_ID_RE.search(out)
        assert m, f"no run id in driver output:\n{out}"
        return m.group(1)

    def deliver_hook(self, token: str, payload) -> None:
        out = self._driver("hook", token, json.dumps(payload))
        assert "HOOK_OK" in out, out

    def worker_logs(self) -> str:
        return "\n".join(f"--- {n} ---\n{p.read_text()}" for n, p in self.logs.items())


def _spawn_worker(env: dict, name: str, queue_flags: list[str], logfile) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pyworkflow.cli",
            "--module",
            APP_MODULE,
            "worker",
            "run",
            *queue_flags,
            "--loglevel",
            "warning",
        ],
        env={**env, "E2E_WORKER_NAME": name, "HOSTNAME": name},
        stdout=logfile,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    base = tmp_path_factory.mktemp("run_strategy_e2e")
    storage_path = str(base / "storage")
    marker_dir = base / "markers"
    marker_dir.mkdir()

    env = os.environ.copy()
    env.update(
        {
            "PYWORKFLOW_CELERY_BROKER": BROKER,
            "PYWORKFLOW_CELERY_RESULT_BACKEND": BROKER,
            "PYWORKFLOW_RUNTIME": "celery",
            "PYWORKFLOW_STORAGE_TYPE": "file",
            "PYWORKFLOW_STORAGE_PATH": storage_path,
            "PYWORKFLOW_MODULE": APP_MODULE,
            "E2E_MARKER_DIR": str(marker_dir),
            "PYTHONPATH": _APP_DIR + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )

    raw = _redis.from_url(BROKER, decode_responses=True)
    raw.flushdb()

    logs = {WF_WORKER: base / "wf_worker.log", STEP_WORKER: base / "step_worker.log"}
    c = Cluster(storage_path=storage_path, marker_dir=marker_dir, env=env, logs=logs)
    procs: list[subprocess.Popen] = []
    with contextlib.ExitStack() as stack:
        files = {n: stack.enter_context(open(p, "w")) for n, p in logs.items()}
        try:
            procs.append(
                _spawn_worker(env, WF_WORKER, ["--workflow", "--schedule"], files[WF_WORKER])
            )
            procs.append(_spawn_worker(env, STEP_WORKER, ["--step"], files[STEP_WORKER]))
            # Readiness probe: a distributed run needs BOTH workers up to complete.
            warm = c.start("s_undeclared", "distributed", n=1)
            final = c.wait_terminal(warm, timeout=90)
            assert final == "completed", f"workers never became ready ({final})\n{c.worker_logs()}"
            yield c
        finally:
            for p in procs:
                _killpg(p)
            raw.flushdb()


# ------------------------------------------------------------------------- tests


class TestStrategyPlacement:
    """Where do steps run? The whole point of the feature."""

    def test_distributed_dispatches_steps_to_the_step_worker(self, cluster: Cluster):
        run_id = cluster.start("s_undeclared", "distributed", n=3)
        assert cluster.wait_terminal(run_id) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == 6

        steps = cluster.steps(run_id)
        assert len(steps) == 3
        assert {s["worker"] for s in steps} == {STEP_WORKER}
        assert all(s["is_step_worker"] for s in steps)

        types = cluster.event_types(run_id)
        assert types.count("step_started") == 3
        assert types.count("step_completed") == 3
        # Each dispatch suspends the workflow task (resumed by the step worker).
        assert types.count("workflow_suspended") == 3

    def test_one_thread_runs_every_step_inline_on_the_workflow_worker(self, cluster: Cluster):
        run_id = cluster.start("s_declared", "none", n=3)
        assert cluster.wait_terminal(run_id) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == 6

        steps = cluster.steps(run_id)
        assert len(steps) == 3
        assert {s["worker"] for s in steps} == {WF_WORKER}
        assert not any(s["is_step_worker"] for s in steps)
        assert {s["strategy"] for s in steps} == {"one_thread"}

        # Same process as the workflow pass itself.
        passes = [t for t in cluster.trace(run_id) if t["event"] == "wf:pass"]
        assert len(passes) == 1, "ONE_THREAD linear run must finish in a single pass"
        assert {s["pid"] for s in steps} == {passes[0]["pid"]}

        types = cluster.event_types(run_id)
        assert "step_started" not in types
        assert types.count("step_completed") == 3
        assert "workflow_suspended" not in types
        assert "workflow_resumed" not in types
        assert types[0] == "workflow_started" and types[-1] == "workflow_completed"

    def test_start_override_switches_undeclared_workflow_to_one_thread(self, cluster: Cluster):
        run_id = cluster.start("s_undeclared", "one_thread", n=3)
        assert cluster.wait_terminal(run_id) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == 6
        assert {s["worker"] for s in cluster.steps(run_id)} == {WF_WORKER}
        assert "step_started" not in cluster.event_types(run_id)

    def test_start_override_switches_declared_workflow_to_distributed(self, cluster: Cluster):
        run_id = cluster.start("s_declared", "distributed", n=2)
        assert cluster.wait_terminal(run_id) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == 3
        assert {s["worker"] for s in cluster.steps(run_id)} == {STEP_WORKER}
        assert cluster.event_types(run_id).count("step_started") == 2

    def test_force_local_still_opts_out_under_distributed(self, cluster: Cluster):
        run_id = cluster.start("s_force_local", "distributed")
        assert cluster.wait_terminal(run_id) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == 4
        by_name = {s["event"]: s for s in cluster.steps(run_id)}
        assert by_name["step:local_add"]["worker"] == WF_WORKER
        assert by_name["step:add"]["worker"] == STEP_WORKER
        # force_local under DISTRIBUTED keeps its STEP_STARTED (unchanged behaviour).
        assert cluster.event_types(run_id).count("step_started") == 2

    def test_persisted_run_records_the_strategy(self, cluster: Cluster):
        """The strategy must be persisted so resume/recover can rebuild it."""
        from pyworkflow.serialization.decoder import deserialize_kwargs

        run_id = cluster.start("s_undeclared", "one_thread", n=1)
        assert cluster.wait_terminal(run_id) == "completed"
        kwargs = deserialize_kwargs(cluster.run(run_id).input_kwargs)
        assert kwargs["_workflow_run_strategy"] == "one_thread"
        assert kwargs["n"] == 1


class TestOneThreadSurvivesSuspension:
    """A ONE_THREAD run still suspends on durable primitives and must resume
    without re-executing steps that already completed in an earlier pass."""

    def test_sleep_resumes_without_re_executing_earlier_steps(self, cluster: Cluster):
        run_id = cluster.start("s_sleep", "none")
        assert cluster.wait_terminal(run_id, timeout=90) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == 12

        steps = cluster.steps(run_id)
        assert [s["event"] for s in steps] == ["step:add", "step:add"], steps
        assert {s["worker"] for s in steps} == {WF_WORKER}
        passes = [t for t in cluster.trace(run_id) if t["event"] == "wf:pass"]
        assert len(passes) == 2, "one pass before the sleep, one after"
        assert {s["strategy"] for s in steps} == {"one_thread"}, "strategy lost on resume"

        types = cluster.event_types(run_id)
        assert "step_started" not in types
        assert types.count("step_completed") == 2
        assert "sleep_started" in types and "sleep_completed" in types

    def test_hook_resumes_with_strategy_intact(self, cluster: Cluster):
        run_id = cluster.start("s_hook", "none")
        assert cluster.wait_status(run_id, "suspended", timeout=60) == "suspended", (
            cluster.worker_logs()
        )
        token = cluster.token(run_id)
        assert token.startswith(f"{run_id}:")
        # Only the pre-hook step has run so far.
        assert [s["event"] for s in cluster.steps(run_id)] == ["step:add"]

        cluster.deliver_hook(token, {"approved": True})
        assert cluster.wait_terminal(run_id) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == {"a": 2, "b": 102, "payload": {"approved": True}}

        steps = cluster.steps(run_id)
        assert [s["event"] for s in steps] == ["step:add", "step:add"], steps
        assert {s["worker"] for s in steps} == {WF_WORKER}
        assert {s["strategy"] for s in steps} == {"one_thread"}
        assert "step_started" not in cluster.event_types(run_id)

    def test_step_hook_inside_inline_step(self, cluster: Cluster):
        run_id = cluster.start("s_step_hook", "none")
        assert cluster.wait_status(run_id, "suspended", timeout=60) == "suspended", (
            cluster.worker_logs()
        )
        token = cluster.token(run_id)
        cluster.deliver_hook(token, {"score": 5})
        assert cluster.wait_terminal(run_id) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == {"feedback": {"score": 5}}

        events = [t["event"] for t in cluster.steps(run_id)]
        # First pass: enters the step, suspends. Second pass: re-enters, gets
        # the payload, finishes. That's the documented step_hook contract.
        assert events == ["step:review", "step:review", "step:review:after_hook"], events
        assert {s["worker"] for s in cluster.steps(run_id)} == {WF_WORKER}
        types = cluster.event_types(run_id)
        assert "step_suspended" in types
        assert "step_started" not in types
        assert types.count("step_completed") == 1

    def test_retry_replays_and_succeeds_inline(self, cluster: Cluster):
        run_id = cluster.start("s_retry", "none")
        assert cluster.wait_terminal(run_id, timeout=90) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == 3

        attempts = [s["attempt"] for s in cluster.steps(run_id)]
        assert attempts == [1, 2, 3], attempts
        assert {s["worker"] for s in cluster.steps(run_id)} == {WF_WORKER}

        types = cluster.event_types(run_id)
        assert "step_started" not in types
        assert types.count("step_failed") == 2
        assert types.count("step_retrying") == 2
        assert types.count("step_completed") == 1

    def test_fatal_error_fails_the_run(self, cluster: Cluster):
        run_id = cluster.start("s_fatal", "none")
        assert cluster.wait_terminal(run_id) == "failed", cluster.worker_logs()
        run = cluster.run(run_id)
        assert "boom" in (run.error or "")
        types = cluster.event_types(run_id)
        assert "step_started" not in types
        assert types.count("step_failed") == 1
        assert "workflow_failed" in types
        assert {s["worker"] for s in cluster.steps(run_id)} == {WF_WORKER}

    def test_concurrent_inline_steps_via_gather(self, cluster: Cluster):
        run_id = cluster.start("s_gather", "none")
        assert cluster.wait_terminal(run_id) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == [2, 4, 6]
        assert {s["worker"] for s in cluster.steps(run_id)} == {WF_WORKER}
        assert cluster.event_types(run_id).count("step_completed") == 3


class TestOneThreadAcrossRuns:
    def test_one_thread_parent_with_one_thread_child(self, cluster: Cluster):
        run_id = cluster.start("s_parent_inline_child", "none")
        assert cluster.wait_terminal(run_id, timeout=90) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == {"a": 2, "child": 3, "b": 5}

        parent_steps = cluster.steps(run_id)
        assert [s["event"] for s in parent_steps] == ["step:add", "step:add"]
        assert {s["worker"] for s in parent_steps} == {WF_WORKER}
        assert {s["strategy"] for s in parent_steps} == {"one_thread"}, (
            "parent lost ONE_THREAD when resumed after the child completed"
        )
        assert "step_started" not in cluster.event_types(run_id)
        assert "child_workflow_completed" in cluster.event_types(run_id)

        children = [r for r in cluster.list_runs() if r.parent_run_id == run_id]
        assert len(children) == 1, children
        child = children[0]
        assert cluster.status(child.run_id) == "completed"
        child_steps = cluster.steps(child.run_id)
        assert len(child_steps) == 2
        assert {s["worker"] for s in child_steps} == {WF_WORKER}
        assert {s["strategy"] for s in child_steps} == {"one_thread"}
        assert "step_started" not in cluster.event_types(child.run_id)

    def test_one_thread_parent_with_distributed_child(self, cluster: Cluster):
        """The parent's ONE_THREAD is NOT inherited by an undeclared child: the
        child runs DISTRIBUTED (its own declaration decides). The child then
        completes on the resume path, and the parent must get the bare result."""
        run_id = cluster.start("s_parent", "none")
        assert cluster.wait_terminal(run_id, timeout=90) == "completed", cluster.worker_logs()
        assert cluster.result(run_id) == {"a": 2, "child": 3, "b": 5}

        parent_steps = cluster.steps(run_id)
        assert [s["event"] for s in parent_steps] == ["step:add", "step:add"]
        assert {s["worker"] for s in parent_steps} == {WF_WORKER}
        assert {s["strategy"] for s in parent_steps} == {"one_thread"}

        children = [r for r in cluster.list_runs() if r.parent_run_id == run_id]
        assert len(children) == 1
        assert cluster.status(children[0].run_id) == "completed"
        child_steps = cluster.steps(children[0].run_id)
        assert {s["worker"] for s in child_steps} == {STEP_WORKER}
        assert {s["strategy"] for s in child_steps} == {"distributed"}
        assert "step_started" in cluster.event_types(children[0].run_id)


class TestLatency:
    def test_one_thread_is_faster_than_distributed_for_many_cheap_steps(self, cluster: Cluster):
        n = 20

        def _timed(strategy: str) -> float:
            run_id = cluster.start("s_many", strategy, n=n)
            assert cluster.wait_terminal(run_id, timeout=120) == "completed", cluster.worker_logs()
            assert cluster.result(run_id) == 5 * n
            events = cluster.events(run_id)
            assert sum(e.type.value == "step.completed" for e in events) == n
            first = next(e for e in events if e.type.value == "workflow.started")
            last = next(e for e in events if e.type.value == "workflow.completed")
            return (last.timestamp - first.timestamp).total_seconds()

        distributed = _timed("distributed")
        one_thread = _timed("one_thread")
        print(
            f"\n[latency] {n} x 5ms steps: distributed={distributed:.3f}s one_thread={one_thread:.3f}s"
        )
        # Not a benchmark, a sanity check: one pass must beat n broker round trips.
        assert one_thread < distributed
