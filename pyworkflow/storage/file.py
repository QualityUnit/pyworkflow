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
        schedules/
            {schedule_id}.json
        _token_index.json  (token -> hook_id mapping)
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

from pyworkflow.engine.events import Event, EventType
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import (
    Hook,
    HookStatus,
    RunStatus,
    Schedule,
    ScheduleStatus,
    StepExecution,
    WorkflowRun,
)


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
        self.schedules_dir = self.base_path / "schedules"
        self.locks_dir = self.base_path / ".locks"
        self._token_index_file = self.base_path / "_token_index.json"

        # Create directories
        for dir_path in [
            self.runs_dir,
            self.events_dir,
            self.steps_dir,
            self.hooks_dir,
            self.schedules_dir,
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

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        """Retrieve a workflow run by ID."""
        run_file = self.runs_dir / f"{run_id}.json"

        if not run_file.exists():
            return None

        lock_file = self.locks_dir / f"{run_id}.lock"
        lock = FileLock(str(lock_file))

        def _read() -> dict | None:
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

    async def get_run_by_idempotency_key(self, key: str) -> WorkflowRun | None:
        """Retrieve a workflow run by idempotency key."""

        def _search() -> dict | None:
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
        result: str | None = None,
        error: str | None = None,
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

    async def update_run_recovery_attempts(
        self,
        run_id: str,
        recovery_attempts: int,
    ) -> None:
        """Update the recovery attempts counter for a workflow run."""
        run_file = self.runs_dir / f"{run_id}.json"

        if not run_file.exists():
            raise ValueError(f"Workflow run {run_id} not found")

        lock_file = self.locks_dir / f"{run_id}.lock"
        lock = FileLock(str(lock_file))

        def _update() -> None:
            with lock:
                data = json.loads(run_file.read_text())
                data["recovery_attempts"] = recovery_attempts
                data["updated_at"] = datetime.now(UTC).isoformat()
                run_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_update)

    async def update_run_context(
        self,
        run_id: str,
        context: dict,
    ) -> None:
        """Update the step context for a workflow run."""
        run_file = self.runs_dir / f"{run_id}.json"

        if not run_file.exists():
            raise ValueError(f"Workflow run {run_id} not found")

        lock_file = self.locks_dir / f"{run_id}.lock"
        lock = FileLock(str(lock_file))

        def _update() -> None:
            with lock:
                data = json.loads(run_file.read_text())
                data["context"] = context
                data["updated_at"] = datetime.now(UTC).isoformat()
                run_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_update)

    async def get_run_context(self, run_id: str) -> dict:
        """Get the current step context for a workflow run."""
        run = await self.get_run(run_id)
        return run.context if run else {}

    async def list_runs(
        self,
        query: str | None = None,
        status: RunStatus | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[WorkflowRun], str | None]:
        """List workflow runs with optional filtering and cursor-based pagination."""

        def _list() -> tuple[list[dict], str | None]:
            runs = []
            query_lower = query.lower() if query else None

            for run_file in self.runs_dir.glob("*.json"):
                data = json.loads(run_file.read_text())

                # Apply query filter (case-insensitive substring in workflow_name or input_kwargs)
                if query_lower:
                    workflow_name = data.get("workflow_name", "").lower()
                    input_kwargs = json.dumps(data.get("input_kwargs", {})).lower()
                    if query_lower not in workflow_name and query_lower not in input_kwargs:
                        continue

                # Apply status filter
                if status and data.get("status") != status.value:
                    continue

                # Apply time filters (based on started_at)
                started_at_str = data.get("started_at")
                if started_at_str:
                    started_at = datetime.fromisoformat(started_at_str)
                    # Make timezone-aware comparison if needed
                    if start_time and started_at < start_time:
                        continue
                    if end_time and started_at >= end_time:
                        continue
                elif start_time or end_time:
                    # If run hasn't started yet and we have time filters, skip it
                    continue

                runs.append(data)

            # Sort by (created_at DESC, run_id DESC) for deterministic ordering
            runs.sort(key=lambda r: (r.get("created_at", ""), r.get("run_id", "")), reverse=True)

            # Apply cursor-based pagination
            if cursor:
                # Find the cursor position and start after it
                cursor_found = False
                filtered_runs = []
                for run in runs:
                    if cursor_found:
                        filtered_runs.append(run)
                    elif run.get("run_id") == cursor:
                        cursor_found = True
                runs = filtered_runs

            # Apply limit and determine next_cursor
            if len(runs) > limit:
                result_runs = runs[:limit]
                next_cursor = result_runs[-1].get("run_id") if result_runs else None
            else:
                result_runs = runs[:limit]
                next_cursor = None

            return result_runs, next_cursor

        run_data_list, next_cursor = await asyncio.to_thread(_list)
        return [WorkflowRun.from_dict(data) for data in run_data_list], next_cursor

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
        event_types: list[str] | None = None,
    ) -> list[Event]:
        """Retrieve all events for a workflow run."""
        events_file = self.events_dir / f"{run_id}.jsonl"

        if not events_file.exists():
            return []

        def _read() -> list[Event]:
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

            return sorted(events, key=lambda e: e.sequence or 0)

        return await asyncio.to_thread(_read)

    async def get_latest_event(
        self,
        run_id: str,
        event_type: str | None = None,
    ) -> Event | None:
        """Get the latest event for a run."""
        events = await self.get_events(run_id, event_types=[event_type] if event_type else None)
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

    async def get_step(self, step_id: str) -> StepExecution | None:
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
        result: str | None = None,
        error: str | None = None,
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

    async def list_steps(self, run_id: str) -> list[StepExecution]:
        """List all steps for a workflow run."""

        def _list() -> list[dict]:
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

    def _load_token_index(self) -> dict:
        """Load the token -> hook_id index."""
        if self._token_index_file.exists():
            return json.loads(self._token_index_file.read_text())
        return {}

    def _save_token_index(self, index: dict) -> None:
        """Save the token -> hook_id index."""
        self._token_index_file.write_text(json.dumps(index, indent=2))

    async def create_hook(self, hook: Hook) -> None:
        """Create a hook record."""
        hook_file = self.hooks_dir / f"{hook.hook_id}.json"
        lock_file = self.locks_dir / "token_index.lock"
        lock = FileLock(str(lock_file))

        data = hook.to_dict()

        def _write() -> None:
            with lock:
                hook_file.write_text(json.dumps(data, indent=2))
                # Update token index
                index = self._load_token_index()
                index[hook.token] = hook.hook_id
                self._save_token_index(index)

        await asyncio.to_thread(_write)

    async def get_hook(self, hook_id: str) -> Hook | None:
        """Retrieve a hook by ID."""
        hook_file = self.hooks_dir / f"{hook_id}.json"

        if not hook_file.exists():
            return None

        def _read() -> dict:
            return json.loads(hook_file.read_text())

        data = await asyncio.to_thread(_read)
        return Hook.from_dict(data)

    async def get_hook_by_token(self, token: str) -> Hook | None:
        """Retrieve a hook by its token."""

        def _lookup() -> str | None:
            index = self._load_token_index()
            return index.get(token)

        hook_id = await asyncio.to_thread(_lookup)
        if hook_id:
            return await self.get_hook(hook_id)
        return None

    async def update_hook_status(
        self,
        hook_id: str,
        status: HookStatus,
        payload: str | None = None,
    ) -> None:
        """Update hook status and optionally payload."""
        hook_file = self.hooks_dir / f"{hook_id}.json"

        if not hook_file.exists():
            raise ValueError(f"Hook {hook_id} not found")

        lock_file = self.locks_dir / f"hook_{hook_id}.lock"
        lock = FileLock(str(lock_file))

        def _update() -> None:
            with lock:
                data = json.loads(hook_file.read_text())
                data["status"] = status.value

                if payload is not None:
                    data["payload"] = payload

                if status == HookStatus.RECEIVED:
                    data["received_at"] = datetime.now(UTC).isoformat()

                hook_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_update)

    async def list_hooks(
        self,
        run_id: str | None = None,
        status: HookStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Hook]:
        """List hooks with optional filtering."""

        def _list() -> list[dict]:
            hooks = []
            for hook_file in self.hooks_dir.glob("*.json"):
                data = json.loads(hook_file.read_text())

                # Apply filters
                if run_id and data.get("run_id") != run_id:
                    continue
                if status and data.get("status") != status.value:
                    continue

                hooks.append(data)

            # Sort by created_at descending
            hooks.sort(key=lambda h: h.get("created_at", ""), reverse=True)

            # Apply pagination
            return hooks[offset : offset + limit]

        hook_data_list = await asyncio.to_thread(_list)
        return [Hook.from_dict(data) for data in hook_data_list]

    # Cancellation Flag Operations

    async def set_cancellation_flag(self, run_id: str) -> None:
        """Set a cancellation flag for a workflow run."""
        cancel_file = self.runs_dir / f"{run_id}.cancel"
        lock_file = self.locks_dir / f"{run_id}_cancel.lock"
        lock = FileLock(str(lock_file))

        def _write() -> None:
            with lock:
                cancel_file.write_text(datetime.now(UTC).isoformat())

        await asyncio.to_thread(_write)

    async def check_cancellation_flag(self, run_id: str) -> bool:
        """Check if a cancellation flag is set for a workflow run."""
        cancel_file = self.runs_dir / f"{run_id}.cancel"

        def _check() -> bool:
            return cancel_file.exists()

        return await asyncio.to_thread(_check)

    async def clear_cancellation_flag(self, run_id: str) -> None:
        """Clear the cancellation flag for a workflow run."""
        cancel_file = self.runs_dir / f"{run_id}.cancel"
        lock_file = self.locks_dir / f"{run_id}_cancel.lock"
        lock = FileLock(str(lock_file))

        def _clear() -> None:
            with lock:
                if cancel_file.exists():
                    cancel_file.unlink()

        await asyncio.to_thread(_clear)

    # Continue-As-New Chain Operations

    async def update_run_continuation(
        self,
        run_id: str,
        continued_to_run_id: str,
    ) -> None:
        """Update the continuation link for a workflow run."""
        run_file = self.runs_dir / f"{run_id}.json"

        if not run_file.exists():
            raise ValueError(f"Workflow run {run_id} not found")

        lock_file = self.locks_dir / f"{run_id}.lock"
        lock = FileLock(str(lock_file))

        def _update() -> None:
            with lock:
                data = json.loads(run_file.read_text())
                data["continued_to_run_id"] = continued_to_run_id
                data["updated_at"] = datetime.now(UTC).isoformat()
                run_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_update)

    async def get_workflow_chain(
        self,
        run_id: str,
    ) -> list[WorkflowRun]:
        """Get all runs in a continue-as-new chain."""
        run = await self.get_run(run_id)
        if not run:
            return []

        # Walk backwards to find the start of the chain
        current = run
        while current.continued_from_run_id:
            prev = await self.get_run(current.continued_from_run_id)
            if not prev:
                break
            current = prev

        # Build chain from start to end
        chain = [current]
        while current.continued_to_run_id:
            next_run = await self.get_run(current.continued_to_run_id)
            if not next_run:
                break
            chain.append(next_run)
            current = next_run

        return chain

    # Child Workflow Operations

    async def get_children(
        self,
        parent_run_id: str,
        status: RunStatus | None = None,
    ) -> list[WorkflowRun]:
        """Get all child workflow runs for a parent workflow."""

        def _list() -> list[dict]:
            children = []
            for run_file in self.runs_dir.glob("*.json"):
                data = json.loads(run_file.read_text())

                # Filter by parent_run_id
                if data.get("parent_run_id") != parent_run_id:
                    continue

                # Filter by status if provided
                if status and data.get("status") != status.value:
                    continue

                children.append(data)

            # Sort by created_at
            children.sort(key=lambda r: r.get("created_at", ""))
            return children

        child_data_list = await asyncio.to_thread(_list)
        return [WorkflowRun.from_dict(data) for data in child_data_list]

    async def get_parent(self, run_id: str) -> WorkflowRun | None:
        """Get the parent workflow run for a child workflow."""
        run = await self.get_run(run_id)
        if run and run.parent_run_id:
            return await self.get_run(run.parent_run_id)
        return None

    async def get_nesting_depth(self, run_id: str) -> int:
        """Get the nesting depth for a workflow."""
        run = await self.get_run(run_id)
        return run.nesting_depth if run else 0

    # Schedule Operations

    async def create_schedule(self, schedule: Schedule) -> None:
        """Create a new schedule record."""
        schedule_file = self.schedules_dir / f"{schedule.schedule_id}.json"

        if schedule_file.exists():
            raise ValueError(f"Schedule {schedule.schedule_id} already exists")

        data = schedule.to_dict()

        lock_file = self.locks_dir / f"schedule_{schedule.schedule_id}.lock"
        lock = FileLock(str(lock_file))

        def _write() -> None:
            with lock:
                schedule_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_write)

    async def get_schedule(self, schedule_id: str) -> Schedule | None:
        """Retrieve a schedule by ID."""
        schedule_file = self.schedules_dir / f"{schedule_id}.json"

        if not schedule_file.exists():
            return None

        lock_file = self.locks_dir / f"schedule_{schedule_id}.lock"
        lock = FileLock(str(lock_file))

        def _read() -> dict | None:
            with lock:
                if not schedule_file.exists():
                    return None
                return json.loads(schedule_file.read_text())

        data = await asyncio.to_thread(_read)
        return Schedule.from_dict(data) if data else None

    async def update_schedule(self, schedule: Schedule) -> None:
        """Update an existing schedule."""
        schedule_file = self.schedules_dir / f"{schedule.schedule_id}.json"

        if not schedule_file.exists():
            raise ValueError(f"Schedule {schedule.schedule_id} does not exist")

        data = schedule.to_dict()

        lock_file = self.locks_dir / f"schedule_{schedule.schedule_id}.lock"
        lock = FileLock(str(lock_file))

        def _write() -> None:
            with lock:
                schedule_file.write_text(json.dumps(data, indent=2))

        await asyncio.to_thread(_write)

    async def delete_schedule(self, schedule_id: str) -> None:
        """Mark a schedule as deleted (soft delete)."""
        schedule = await self.get_schedule(schedule_id)

        if not schedule:
            raise ValueError(f"Schedule {schedule_id} does not exist")

        schedule.status = ScheduleStatus.DELETED
        schedule.updated_at = datetime.now(UTC)
        await self.update_schedule(schedule)

    async def list_schedules(
        self,
        workflow_name: str | None = None,
        status: ScheduleStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Schedule]:
        """List schedules with optional filtering."""

        def _list() -> list[dict]:
            schedules = []
            for schedule_file in self.schedules_dir.glob("*.json"):
                try:
                    data = json.loads(schedule_file.read_text())

                    # Apply filters
                    if workflow_name and data.get("workflow_name") != workflow_name:
                        continue
                    if status and data.get("status") != status.value:
                        continue

                    schedules.append(data)
                except (json.JSONDecodeError, KeyError):
                    continue

            # Sort by created_at descending
            schedules.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            # Apply pagination
            return schedules[offset : offset + limit]

        schedule_data_list = await asyncio.to_thread(_list)
        return [Schedule.from_dict(data) for data in schedule_data_list]

    async def get_due_schedules(self, now: datetime) -> list[Schedule]:
        """Get all schedules that are due to run."""
        now_iso = now.isoformat()

        def _list_due() -> list[dict]:
            due_schedules = []
            for schedule_file in self.schedules_dir.glob("*.json"):
                try:
                    data = json.loads(schedule_file.read_text())

                    # Check criteria
                    if data.get("status") != ScheduleStatus.ACTIVE.value:
                        continue
                    next_run = data.get("next_run_time")
                    if not next_run:
                        continue
                    if next_run > now_iso:
                        continue

                    due_schedules.append(data)
                except (json.JSONDecodeError, KeyError):
                    continue

            # Sort by next_run_time ascending
            due_schedules.sort(key=lambda x: x.get("next_run_time", ""))
            return due_schedules

        schedule_data_list = await asyncio.to_thread(_list_due)
        return [Schedule.from_dict(data) for data in schedule_data_list]

    async def add_running_run(self, schedule_id: str, run_id: str) -> None:
        """Add a run_id to the schedule's running_run_ids list."""
        schedule = await self.get_schedule(schedule_id)

        if not schedule:
            raise ValueError(f"Schedule {schedule_id} does not exist")

        if run_id not in schedule.running_run_ids:
            schedule.running_run_ids.append(run_id)
            schedule.updated_at = datetime.now(UTC)
            await self.update_schedule(schedule)

    async def remove_running_run(self, schedule_id: str, run_id: str) -> None:
        """Remove a run_id from the schedule's running_run_ids list."""
        schedule = await self.get_schedule(schedule_id)

        if not schedule:
            raise ValueError(f"Schedule {schedule_id} does not exist")

        if run_id in schedule.running_run_ids:
            schedule.running_run_ids.remove(run_id)
            schedule.updated_at = datetime.now(UTC)
            await self.update_schedule(schedule)
