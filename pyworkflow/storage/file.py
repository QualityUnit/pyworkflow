"""
File-based storage backend using JSON files.

This backend stores workflow data in local JSON files, suitable for:
- Development and testing
- Single-machine deployments
- Low-volume production use

Data is stored in a directory structure:
    base_path/
        runs/
            {run_id}.json
        events/
            {run_id}.jsonl  (append-only)
        steps/
            {step_id}.json
        hooks/
            {hook_id}.json
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import List, Optional

from filelock import FileLock

from pyworkflow.engine.events import Event, EventType
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import Hook, HookStatus, RunStatus, StepExecution, WorkflowRun


class FileStorageBackend(StorageBackend):
    """
    File-based storage backend using JSON files.

    Thread-safe using file locks for concurrent access.
    """

    def __init__(self, base_path: str = "./pyworkflow_data"):
        """
        Initialize file storage backend.

        Args:
            base_path: Base directory for storing workflow data
        """
        self.base_path = Path(base_path)
        self.runs_dir = self.base_path / "runs"
        self.events_dir = self.base_path / "events"
        self.steps_dir = self.base_path / "steps"
        self.hooks_dir = self.base_path / "hooks"
        self.locks_dir = self.base_path / ".locks"

        # Create directories
        for dir_path in [
            self.runs_dir,
            self.events_dir,
            self.steps_dir,
            self.hooks_dir,
            self.locks_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)

    # Workflow Run Operations

    async def create_run(self, run: WorkflowRun) -> None:
        """Create a new workflow run record."""
        run_file = self.runs_dir / f"{run.run_id}.json"

        if run_file.exists():
            raise ValueError(f"Workflow run {run.run_id} already exists")

        data = run.to_dict()

        # Use file lock for thread safety
        lock_file = self.locks_dir / f"{run.run_id}.lock"
        lock = FileLock(str(lock_file))

        def _write() -> None:
            with lock:
                run_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_write)

    async def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        """Retrieve a workflow run by ID."""
        run_file = self.runs_dir / f"{run_id}.json"

        if not run_file.exists():
            return None

        lock_file = self.locks_dir / f"{run_id}.lock"
        lock = FileLock(str(lock_file))

        def _read() -> Optional[dict]:
            with lock:
                if not run_file.exists():
                    return None
                content = run_file.read_text()
                if not content.strip():
                    # File exists but is empty (race condition) - treat as not found
                    return None
                return json.loads(content)

        data = await asyncio.to_thread(_read)
        return WorkflowRun.from_dict(data) if data else None

    async def get_run_by_idempotency_key(self, key: str) -> Optional[WorkflowRun]:
        """Retrieve a workflow run by idempotency key."""

        def _search() -> Optional[dict]:
            for run_file in self.runs_dir.glob("*.json"):
                data = json.loads(run_file.read_text())
                if data.get("idempotency_key") == key:
                    return data
            return None

        data = await asyncio.to_thread(_search)
        return WorkflowRun.from_dict(data) if data else None

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update workflow run status."""
        run_file = self.runs_dir / f"{run_id}.json"

        if not run_file.exists():
            raise ValueError(f"Workflow run {run_id} not found")

        lock_file = self.locks_dir / f"{run_id}.lock"
        lock = FileLock(str(lock_file))

        def _update() -> None:
            with lock:
                data = json.loads(run_file.read_text())
                data["status"] = status.value
                data["updated_at"] = datetime.now(UTC).isoformat()

                if result is not None:
                    data["result"] = result

                if error is not None:
                    data["error"] = error

                if status == RunStatus.COMPLETED:
                    data["completed_at"] = datetime.now(UTC).isoformat()

                run_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_update)

    async def list_runs(
        self,
        workflow_name: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[WorkflowRun]:
        """List workflow runs with optional filtering."""

        def _list() -> List[dict]:
            runs = []
            for run_file in self.runs_dir.glob("*.json"):
                data = json.loads(run_file.read_text())

                # Apply filters
                if workflow_name and data.get("workflow_name") != workflow_name:
                    continue
                if status and data.get("status") != status.value:
                    continue

                runs.append(data)

            # Sort by created_at descending
            runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)

            # Apply pagination
            return runs[offset : offset + limit]

        run_data_list = await asyncio.to_thread(_list)
        return [WorkflowRun.from_dict(data) for data in run_data_list]

    # Event Log Operations

    async def record_event(self, event: Event) -> None:
        """Record an event to the append-only event log."""
        events_file = self.events_dir / f"{event.run_id}.jsonl"
        lock_file = self.locks_dir / f"events_{event.run_id}.lock"
        lock = FileLock(str(lock_file))

        def _append() -> None:
            with lock:
                # Get next sequence number
                sequence = 1
                if events_file.exists():
                    with events_file.open("r") as f:
                        for line in f:
                            if line.strip():
                                sequence += 1

                event.sequence = sequence

                # Append event
                event_data = {
                    "event_id": event.event_id,
                    "run_id": event.run_id,
                    "type": event.type.value,
                    "sequence": event.sequence,
                    "timestamp": event.timestamp.isoformat(),
                    "data": event.data,
                }

                with events_file.open("a") as f:
                    f.write(json.dumps(event_data) + "\n")

        await asyncio.to_thread(_append)

    async def get_events(
        self,
        run_id: str,
        event_types: Optional[List[str]] = None,
    ) -> List[Event]:
        """Retrieve all events for a workflow run."""
        events_file = self.events_dir / f"{run_id}.jsonl"

        if not events_file.exists():
            return []

        def _read() -> List[Event]:
            events = []
            with events_file.open("r") as f:
                for line in f:
                    if not line.strip():
                        continue

                    data = json.loads(line)

                    # Apply type filter
                    if event_types and data["type"] not in event_types:
                        continue

                    events.append(
                        Event(
                            event_id=data["event_id"],
                            run_id=data["run_id"],
                            type=EventType(data["type"]),
                            sequence=data["sequence"],
                            timestamp=datetime.fromisoformat(data["timestamp"]),
                            data=data["data"],
                        )
                    )

            return sorted(events, key=lambda e: e.sequence)

        return await asyncio.to_thread(_read)

    async def get_latest_event(
        self,
        run_id: str,
        event_type: Optional[str] = None,
    ) -> Optional[Event]:
        """Get the latest event for a run."""
        events = await self.get_events(
            run_id, event_types=[event_type] if event_type else None
        )
        return events[-1] if events else None

    # Step Operations

    async def create_step(self, step: StepExecution) -> None:
        """Create a step execution record."""
        step_file = self.steps_dir / f"{step.step_id}.json"

        if step_file.exists():
            raise ValueError(f"Step {step.step_id} already exists")

        data = step.to_dict()

        def _write() -> None:
            step_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_write)

    async def get_step(self, step_id: str) -> Optional[StepExecution]:
        """Retrieve a step execution by ID."""
        step_file = self.steps_dir / f"{step_id}.json"

        if not step_file.exists():
            return None

        def _read() -> dict:
            return json.loads(step_file.read_text())

        data = await asyncio.to_thread(_read)
        return StepExecution.from_dict(data)

    async def update_step_status(
        self,
        step_id: str,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update step execution status."""
        step_file = self.steps_dir / f"{step_id}.json"

        if not step_file.exists():
            raise ValueError(f"Step {step_id} not found")

        def _update() -> None:
            data = json.loads(step_file.read_text())
            data["status"] = status
            data["updated_at"] = datetime.utcnow().isoformat()

            if result is not None:
                data["result"] = result

            if error is not None:
                data["error"] = error

            if status == "completed":
                data["completed_at"] = datetime.utcnow().isoformat()

            step_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_update)

    async def list_steps(self, run_id: str) -> List[StepExecution]:
        """List all steps for a workflow run."""

        def _list() -> List[dict]:
            steps = []
            for step_file in self.steps_dir.glob("*.json"):
                data = json.loads(step_file.read_text())
                if data.get("run_id") == run_id:
                    steps.append(data)

            # Sort by created_at
            steps.sort(key=lambda s: s.get("created_at", ""))
            return steps

        step_data_list = await asyncio.to_thread(_list)
        return [StepExecution.from_dict(data) for data in step_data_list]

    # Hook Operations

    async def create_hook(self, hook: Hook) -> None:
        """Create a hook record."""
        hook_file = self.hooks_dir / f"{hook.hook_id}.json"

        if hook_file.exists():
            raise ValueError(f"Hook {hook.hook_id} already exists")

        data = hook.to_dict()

        def _write() -> None:
            hook_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_write)

    async def get_hook(self, hook_id: str) -> Optional[Hook]:
        """Retrieve a hook by ID."""
        hook_file = self.hooks_dir / f"{hook_id}.json"

        if not hook_file.exists():
            return None

        def _read() -> dict:
            return json.loads(hook_file.read_text())

        data = await asyncio.to_thread(_read)
        return Hook.from_dict(data)

    async def get_hook_by_token(self, run_id: str, token: str) -> Optional[Hook]:
        """Retrieve a hook by run_id and token."""

        def _search() -> Optional[dict]:
            for hook_file in self.hooks_dir.glob("*.json"):
                data = json.loads(hook_file.read_text())
                if data.get("run_id") == run_id and data.get("token") == token:
                    return data
            return None

        data = await asyncio.to_thread(_search)
        return Hook.from_dict(data) if data else None

    async def update_hook_payload(
        self,
        hook_id: str,
        payload: str,
        status: Optional[str] = None,
    ) -> None:
        """Update hook with received payload."""
        hook_file = self.hooks_dir / f"{hook_id}.json"

        if not hook_file.exists():
            raise ValueError(f"Hook {hook_id} not found")

        def _update() -> None:
            data = json.loads(hook_file.read_text())
            data["payload"] = payload
            data["received_at"] = datetime.now(UTC).isoformat()

            if status:
                data["status"] = status
            else:
                data["status"] = HookStatus.RECEIVED.value

            hook_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_update)

    async def list_hooks(self, run_id: str) -> List[Hook]:
        """List all hooks for a workflow run."""

        def _list() -> List[dict]:
            hooks = []
            for hook_file in self.hooks_dir.glob("*.json"):
                data = json.loads(hook_file.read_text())
                if data.get("run_id") == run_id:
                    hooks.append(data)

            # Sort by created_at
            hooks.sort(key=lambda h: h.get("created_at", ""))
            return hooks

        hook_data_list = await asyncio.to_thread(_list)
        return [Hook.from_dict(data) for data in hook_data_list]
