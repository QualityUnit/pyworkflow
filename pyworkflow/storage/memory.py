"""
In-memory storage backend for testing and transient workflows.

This backend stores all data in memory and is ideal for:
- Unit testing
- Transient workflows that don't need persistence
- Development and prototyping
- Ephemeral containers

Note: All data is lost when the process exits.
"""

import threading
from datetime import UTC, datetime

from pyworkflow.engine.events import Event
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


class InMemoryStorageBackend(StorageBackend):
    """
    Thread-safe in-memory storage backend.

    All data is stored in dictionaries and protected by a reentrant lock
    for thread safety.

    Example:
        >>> storage = InMemoryStorageBackend()
        >>> pyworkflow.configure(storage=storage)
    """

    def __init__(self) -> None:
        """Initialize empty storage."""
        self._runs: dict[str, WorkflowRun] = {}
        self._events: dict[str, list[Event]] = {}
        self._steps: dict[str, StepExecution] = {}
        self._hooks: dict[str, Hook] = {}
        self._schedules: dict[str, Schedule] = {}
        self._idempotency_index: dict[str, str] = {}  # key -> run_id
        self._token_index: dict[str, str] = {}  # token -> hook_id
        self._cancellation_flags: dict[str, bool] = {}  # run_id -> cancelled
        self._lock = threading.RLock()
        self._event_sequences: dict[str, int] = {}  # run_id -> next sequence

    # Workflow Run Operations

    async def create_run(self, run: WorkflowRun) -> None:
        """Create a new workflow run record."""
        with self._lock:
            if run.run_id in self._runs:
                raise ValueError(f"Run {run.run_id} already exists")
            self._runs[run.run_id] = run
            self._events[run.run_id] = []
            self._event_sequences[run.run_id] = 0
            if run.idempotency_key:
                self._idempotency_index[run.idempotency_key] = run.run_id

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        """Retrieve a workflow run by ID."""
        with self._lock:
            return self._runs.get(run_id)

    async def get_run_by_idempotency_key(self, key: str) -> WorkflowRun | None:
        """Retrieve a workflow run by idempotency key."""
        with self._lock:
            run_id = self._idempotency_index.get(key)
            if run_id:
                return self._runs.get(run_id)
            return None

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update workflow run status and optionally result/error."""
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.status = status
                run.updated_at = datetime.now(UTC)
                if result is not None:
                    run.result = result
                if error is not None:
                    run.error = error
                if status == RunStatus.COMPLETED or status == RunStatus.FAILED:
                    run.completed_at = datetime.now(UTC)

    async def update_run_recovery_attempts(
        self,
        run_id: str,
        recovery_attempts: int,
    ) -> None:
        """Update the recovery attempts counter for a workflow run."""
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.recovery_attempts = recovery_attempts
                run.updated_at = datetime.now(UTC)

    async def update_run_context(
        self,
        run_id: str,
        context: dict,
    ) -> None:
        """Update the step context for a workflow run."""
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.context = context
                run.updated_at = datetime.now(UTC)

    async def get_run_context(self, run_id: str) -> dict:
        """Get the current step context for a workflow run."""
        with self._lock:
            run = self._runs.get(run_id)
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
        import json

        with self._lock:
            runs = list(self._runs.values())

            # Filter by query (case-insensitive substring in workflow_name or input_kwargs)
            if query:
                query_lower = query.lower()
                filtered_runs = []
                for r in runs:
                    workflow_name_match = query_lower in r.workflow_name.lower()
                    input_kwargs_str = json.dumps(r.input_kwargs or {}).lower()
                    input_kwargs_match = query_lower in input_kwargs_str
                    if workflow_name_match or input_kwargs_match:
                        filtered_runs.append(r)
                runs = filtered_runs

            # Filter by status
            if status:
                runs = [r for r in runs if r.status == status]

            # Filter by time range (based on started_at)
            if start_time or end_time:
                filtered_runs = []
                for r in runs:
                    if r.started_at is None:
                        continue  # Skip runs that haven't started
                    if start_time and r.started_at < start_time:
                        continue
                    if end_time and r.started_at >= end_time:
                        continue
                    filtered_runs.append(r)
                runs = filtered_runs

            # Sort by (created_at DESC, run_id DESC) for deterministic ordering
            runs.sort(key=lambda r: (r.created_at, r.run_id), reverse=True)

            # Apply cursor-based pagination
            if cursor:
                cursor_found = False
                filtered_runs = []
                for run in runs:
                    if cursor_found:
                        filtered_runs.append(run)
                    elif run.run_id == cursor:
                        cursor_found = True
                runs = filtered_runs

            # Apply limit and determine next_cursor
            if len(runs) > limit:
                result_runs = runs[:limit]
                next_cursor = result_runs[-1].run_id if result_runs else None
            else:
                result_runs = runs[:limit]
                next_cursor = None

            return result_runs, next_cursor

    # Event Log Operations

    async def record_event(self, event: Event) -> None:
        """Record an event to the append-only event log."""
        with self._lock:
            run_id = event.run_id
            if run_id not in self._events:
                self._events[run_id] = []
                self._event_sequences[run_id] = 0

            # Assign sequence number
            event.sequence = self._event_sequences[run_id]
            self._event_sequences[run_id] += 1

            self._events[run_id].append(event)

    async def get_events(
        self,
        run_id: str,
        event_types: list[str] | None = None,
    ) -> list[Event]:
        """Retrieve all events for a workflow run, ordered by sequence."""
        with self._lock:
            events = list(self._events.get(run_id, []))

            # Filter by event types
            if event_types:
                events = [e for e in events if e.type in event_types]

            # Sort by sequence
            events.sort(key=lambda e: e.sequence or 0)

            return events

    async def get_latest_event(
        self,
        run_id: str,
        event_type: str | None = None,
    ) -> Event | None:
        """Get the latest event for a run, optionally filtered by type."""
        with self._lock:
            events = self._events.get(run_id, [])
            if not events:
                return None

            # Filter by event type
            if event_type:
                events = [e for e in events if e.type.value == event_type]

            if not events:
                return None

            # Return event with highest sequence
            return max(events, key=lambda e: e.sequence or 0)

    # Step Operations

    async def create_step(self, step: StepExecution) -> None:
        """Create a step execution record."""
        with self._lock:
            self._steps[step.step_id] = step

    async def get_step(self, step_id: str) -> StepExecution | None:
        """Retrieve a step execution by ID."""
        with self._lock:
            return self._steps.get(step_id)

    async def update_step_status(
        self,
        step_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update step execution status."""
        with self._lock:
            step = self._steps.get(step_id)
            if step:
                from pyworkflow.storage.schemas import StepStatus

                step.status = StepStatus(status)
                step.updated_at = datetime.now(UTC)
                if result is not None:
                    step.result = result
                if error is not None:
                    step.error = error

    async def list_steps(self, run_id: str) -> list[StepExecution]:
        """List all steps for a workflow run."""
        with self._lock:
            return [s for s in self._steps.values() if s.run_id == run_id]

    # Hook Operations

    async def create_hook(self, hook: Hook) -> None:
        """Create a hook record."""
        with self._lock:
            self._hooks[hook.hook_id] = hook
            self._token_index[hook.token] = hook.hook_id

    async def get_hook(self, hook_id: str) -> Hook | None:
        """Retrieve a hook by ID."""
        with self._lock:
            return self._hooks.get(hook_id)

    async def get_hook_by_token(self, token: str) -> Hook | None:
        """Retrieve a hook by its token."""
        with self._lock:
            hook_id = self._token_index.get(token)
            if hook_id:
                return self._hooks.get(hook_id)
            return None

    async def update_hook_status(
        self,
        hook_id: str,
        status: HookStatus,
        payload: str | None = None,
    ) -> None:
        """Update hook status and optionally payload."""
        with self._lock:
            hook = self._hooks.get(hook_id)
            if hook:
                hook.status = status
                if payload is not None:
                    hook.payload = payload
                if status == HookStatus.RECEIVED:
                    hook.received_at = datetime.now(UTC)

    async def list_hooks(
        self,
        run_id: str | None = None,
        status: HookStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Hook]:
        """List hooks with optional filtering."""
        with self._lock:
            hooks = list(self._hooks.values())

            # Filter by run_id
            if run_id:
                hooks = [h for h in hooks if h.run_id == run_id]

            # Filter by status
            if status:
                hooks = [h for h in hooks if h.status == status]

            # Sort by created_at descending
            hooks.sort(key=lambda h: h.created_at, reverse=True)

            # Apply pagination
            return hooks[offset : offset + limit]

    # Cancellation Flag Operations

    async def set_cancellation_flag(self, run_id: str) -> None:
        """Set a cancellation flag for a workflow run."""
        with self._lock:
            self._cancellation_flags[run_id] = True

    async def check_cancellation_flag(self, run_id: str) -> bool:
        """Check if a cancellation flag is set for a workflow run."""
        with self._lock:
            return self._cancellation_flags.get(run_id, False)

    async def clear_cancellation_flag(self, run_id: str) -> None:
        """Clear the cancellation flag for a workflow run."""
        with self._lock:
            self._cancellation_flags.pop(run_id, None)

    # Continue-As-New Chain Operations

    async def update_run_continuation(
        self,
        run_id: str,
        continued_to_run_id: str,
    ) -> None:
        """Update the continuation link for a workflow run."""
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.continued_to_run_id = continued_to_run_id
                run.updated_at = datetime.now(UTC)

    async def get_workflow_chain(
        self,
        run_id: str,
    ) -> list[WorkflowRun]:
        """Get all runs in a continue-as-new chain."""
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return []

            # Walk backwards to find the start of the chain
            current = run
            while current.continued_from_run_id:
                prev = self._runs.get(current.continued_from_run_id)
                if not prev:
                    break
                current = prev

            # Build chain from start to end
            chain = [current]
            while current.continued_to_run_id:
                next_run = self._runs.get(current.continued_to_run_id)
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
        with self._lock:
            children = [run for run in self._runs.values() if run.parent_run_id == parent_run_id]

            if status:
                children = [c for c in children if c.status == status]

            # Sort by created_at
            children.sort(key=lambda r: r.created_at)

            return children

    async def get_parent(self, run_id: str) -> WorkflowRun | None:
        """Get the parent workflow run for a child workflow."""
        with self._lock:
            run = self._runs.get(run_id)
            if run and run.parent_run_id:
                return self._runs.get(run.parent_run_id)
            return None

    async def get_nesting_depth(self, run_id: str) -> int:
        """Get the nesting depth for a workflow."""
        with self._lock:
            run = self._runs.get(run_id)
            return run.nesting_depth if run else 0

    # Schedule Operations

    async def create_schedule(self, schedule: Schedule) -> None:
        """Create a new schedule record."""
        with self._lock:
            if schedule.schedule_id in self._schedules:
                raise ValueError(f"Schedule {schedule.schedule_id} already exists")
            self._schedules[schedule.schedule_id] = schedule

    async def get_schedule(self, schedule_id: str) -> Schedule | None:
        """Retrieve a schedule by ID."""
        with self._lock:
            return self._schedules.get(schedule_id)

    async def update_schedule(self, schedule: Schedule) -> None:
        """Update an existing schedule."""
        with self._lock:
            if schedule.schedule_id not in self._schedules:
                raise ValueError(f"Schedule {schedule.schedule_id} does not exist")
            self._schedules[schedule.schedule_id] = schedule

    async def delete_schedule(self, schedule_id: str) -> None:
        """Mark a schedule as deleted (soft delete)."""
        with self._lock:
            if schedule_id not in self._schedules:
                raise ValueError(f"Schedule {schedule_id} does not exist")
            schedule = self._schedules[schedule_id]
            schedule.status = ScheduleStatus.DELETED
            schedule.updated_at = datetime.now(UTC)

    async def list_schedules(
        self,
        workflow_name: str | None = None,
        status: ScheduleStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Schedule]:
        """List schedules with optional filtering."""
        with self._lock:
            schedules = list(self._schedules.values())

            # Apply filters
            if workflow_name:
                schedules = [s for s in schedules if s.workflow_name == workflow_name]
            if status:
                schedules = [s for s in schedules if s.status == status]

            # Sort by created_at descending
            schedules.sort(key=lambda s: s.created_at, reverse=True)

            # Apply pagination
            return schedules[offset : offset + limit]

    async def get_due_schedules(self, now: datetime) -> list[Schedule]:
        """Get all schedules that are due to run."""
        with self._lock:
            due_schedules = [
                s
                for s in self._schedules.values()
                if s.status == ScheduleStatus.ACTIVE
                and s.next_run_time is not None
                and s.next_run_time <= now
            ]

            # Sort by next_run_time ascending
            due_schedules.sort(key=lambda s: s.next_run_time)  # type: ignore
            return due_schedules

    async def add_running_run(self, schedule_id: str, run_id: str) -> None:
        """Add a run_id to the schedule's running_run_ids list."""
        with self._lock:
            if schedule_id not in self._schedules:
                raise ValueError(f"Schedule {schedule_id} does not exist")
            schedule = self._schedules[schedule_id]
            if run_id not in schedule.running_run_ids:
                schedule.running_run_ids.append(run_id)
                schedule.updated_at = datetime.now(UTC)

    async def remove_running_run(self, schedule_id: str, run_id: str) -> None:
        """Remove a run_id from the schedule's running_run_ids list."""
        with self._lock:
            if schedule_id not in self._schedules:
                raise ValueError(f"Schedule {schedule_id} does not exist")
            schedule = self._schedules[schedule_id]
            if run_id in schedule.running_run_ids:
                schedule.running_run_ids.remove(run_id)
                schedule.updated_at = datetime.now(UTC)

    # Utility methods

    def clear(self) -> None:
        """
        Clear all data from storage.

        Useful for testing to reset state between tests.
        """
        with self._lock:
            self._runs.clear()
            self._events.clear()
            self._steps.clear()
            self._hooks.clear()
            self._schedules.clear()
            self._idempotency_index.clear()
            self._token_index.clear()
            self._cancellation_flags.clear()
            self._event_sequences.clear()

    def __len__(self) -> int:
        """Return total number of workflow runs."""
        with self._lock:
            return len(self._runs)

    def __repr__(self) -> str:
        """Return string representation."""
        with self._lock:
            return (
                f"InMemoryStorageBackend("
                f"runs={len(self._runs)}, "
                f"events={sum(len(e) for e in self._events.values())}, "
                f"steps={len(self._steps)}, "
                f"hooks={len(self._hooks)}, "
                f"schedules={len(self._schedules)})"
            )
