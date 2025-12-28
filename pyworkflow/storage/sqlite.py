"""
SQLite storage backend using aiosqlite.

This backend stores workflow data in a single SQLite database file, suitable for:
- Development and testing
- Single-machine deployments
- Small to medium production workloads

Provides ACID guarantees and efficient querying with SQL indexes.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from pyworkflow.engine.events import Event, EventType
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import (
    Hook,
    HookStatus,
    OverlapPolicy,
    RunStatus,
    Schedule,
    ScheduleSpec,
    ScheduleStatus,
    StepExecution,
    WorkflowRun,
)


class SQLiteStorageBackend(StorageBackend):
    """
    SQLite storage backend using aiosqlite for async operations.

    All workflow data is stored in a single SQLite database file with proper
    indexes for efficient querying.
    """

    def __init__(self, db_path: str = "./pyworkflow_data/pyworkflow.db"):
        """
        Initialize SQLite storage backend.

        Args:
            db_path: Path to SQLite database file (will be created if doesn't exist)
        """
        self.db_path = Path(db_path)
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: aiosqlite.Connection | None = None
        self._initialized = False

    async def connect(self) -> None:
        """Initialize connection and create tables if needed."""
        if self._db is None:
            self._db = await aiosqlite.connect(str(self.db_path))
            # Enable foreign keys
            await self._db.execute("PRAGMA foreign_keys = ON")
            await self._db.commit()

        if not self._initialized:
            await self._initialize_schema()
            self._initialized = True

    async def disconnect(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            self._initialized = False

    async def _initialize_schema(self) -> None:
        """Create database tables if they don't exist."""
        if not self._db:
            await self.connect()

        # At this point self._db is guaranteed to be set
        assert self._db is not None
        db = self._db

        # Workflow runs table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                input_args TEXT NOT NULL DEFAULT '[]',
                input_kwargs TEXT NOT NULL DEFAULT '{}',
                result TEXT,
                error TEXT,
                idempotency_key TEXT,
                max_duration TEXT,
                metadata TEXT DEFAULT '{}',
                recovery_attempts INTEGER DEFAULT 0,
                max_recovery_attempts INTEGER DEFAULT 3,
                recover_on_worker_loss INTEGER DEFAULT 1,
                parent_run_id TEXT,
                nesting_depth INTEGER DEFAULT 0,
                continued_from_run_id TEXT,
                continued_to_run_id TEXT,
                FOREIGN KEY (parent_run_id) REFERENCES workflow_runs(run_id)
            )
        """)

        # Indexes for workflow_runs
        await db.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON workflow_runs(status)")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_workflow_name ON workflow_runs(workflow_name)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_created_at ON workflow_runs(created_at DESC)"
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency_key ON workflow_runs(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_parent_run_id ON workflow_runs(parent_run_id)"
        )

        # Events table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                type TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                data TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
            )
        """)

        # Indexes for events
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_run_id_sequence ON events(run_id, sequence)"
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(type)")

        # Steps table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS steps (
                step_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                input_args TEXT NOT NULL DEFAULT '[]',
                input_kwargs TEXT NOT NULL DEFAULT '{}',
                result TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
            )
        """)

        # Indexes for steps
        await db.execute("CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps(run_id)")

        # Hooks table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS hooks (
                hook_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP NOT NULL,
                received_at TIMESTAMP,
                expires_at TIMESTAMP,
                status TEXT NOT NULL,
                payload TEXT,
                metadata TEXT DEFAULT '{}',
                FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
            )
        """)

        # Indexes for hooks
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_hooks_token ON hooks(token)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hooks_run_id ON hooks(run_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_hooks_status ON hooks(status)")

        # Schedules table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                schedule_id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                spec TEXT NOT NULL,
                spec_type TEXT NOT NULL,
                timezone TEXT,
                input_args TEXT NOT NULL DEFAULT '[]',
                input_kwargs TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                overlap_policy TEXT NOT NULL,
                next_run_time TIMESTAMP,
                last_run_time TIMESTAMP,
                running_run_ids TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                paused_at TIMESTAMP,
                deleted_at TIMESTAMP
            )
        """)

        # Indexes for schedules
        await db.execute("CREATE INDEX IF NOT EXISTS idx_schedules_status ON schedules(status)")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedules_next_run_time ON schedules(next_run_time)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedules_workflow_name ON schedules(workflow_name)"
        )

        # Cancellation flags table (simple key-value for run cancellation)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cancellation_flags (
                run_id TEXT PRIMARY KEY,
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
            )
        """)

        await db.commit()

    def _ensure_connected(self) -> aiosqlite.Connection:
        """Ensure database is connected."""
        if not self._db:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    # Workflow Run Operations

    async def create_run(self, run: WorkflowRun) -> None:
        """Create a new workflow run record."""
        db = self._ensure_connected()

        await db.execute(
            """
            INSERT INTO workflow_runs (
                run_id, workflow_name, status, created_at, updated_at, started_at,
                completed_at, input_args, input_kwargs, result, error, idempotency_key,
                max_duration, metadata, recovery_attempts, max_recovery_attempts,
                recover_on_worker_loss, parent_run_id, nesting_depth,
                continued_from_run_id, continued_to_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.workflow_name,
                run.status.value,
                run.created_at.isoformat(),
                run.updated_at.isoformat(),
                run.started_at.isoformat() if run.started_at else None,
                run.completed_at.isoformat() if run.completed_at else None,
                run.input_args,
                run.input_kwargs,
                run.result,
                run.error,
                run.idempotency_key,
                run.max_duration,
                json.dumps(run.context),
                run.recovery_attempts,
                run.max_recovery_attempts,
                1 if run.recover_on_worker_loss else 0,
                run.parent_run_id,
                run.nesting_depth,
                run.continued_from_run_id,
                run.continued_to_run_id,
            ),
        )
        await db.commit()

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        """Retrieve a workflow run by ID."""
        db = self._ensure_connected()

        async with db.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_workflow_run(row)

    async def get_run_by_idempotency_key(self, key: str) -> WorkflowRun | None:
        """Retrieve a workflow run by idempotency key."""
        db = self._ensure_connected()

        async with db.execute(
            "SELECT * FROM workflow_runs WHERE idempotency_key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_workflow_run(row)

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update workflow run status."""
        db = self._ensure_connected()

        now = datetime.now(UTC).isoformat()
        completed_at = now if status == RunStatus.COMPLETED else None

        # Build dynamic query
        updates = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status.value, now]

        if result is not None:
            updates.append("result = ?")
            params.append(result)

        if error is not None:
            updates.append("error = ?")
            params.append(error)

        if completed_at:
            updates.append("completed_at = ?")
            params.append(completed_at)

        params.append(run_id)

        await db.execute(
            f"UPDATE workflow_runs SET {', '.join(updates)} WHERE run_id = ?",
            tuple(params),
        )
        await db.commit()

    async def update_run_recovery_attempts(
        self,
        run_id: str,
        recovery_attempts: int,
    ) -> None:
        """Update the recovery attempts counter for a workflow run."""
        db = self._ensure_connected()

        await db.execute(
            """
            UPDATE workflow_runs
            SET recovery_attempts = ?, updated_at = ?
            WHERE run_id = ?
            """,
            (recovery_attempts, datetime.now(UTC).isoformat(), run_id),
        )
        await db.commit()

    async def update_run_context(
        self,
        run_id: str,
        context: dict,
    ) -> None:
        """Update the step context for a workflow run."""
        db = self._ensure_connected()

        await db.execute(
            """
            UPDATE workflow_runs
            SET metadata = ?, updated_at = ?
            WHERE run_id = ?
            """,
            (json.dumps(context), datetime.now(UTC).isoformat(), run_id),
        )
        await db.commit()

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
        """List workflow runs with optional filtering and pagination."""
        db = self._ensure_connected()

        conditions = []
        params: list[Any] = []

        if cursor:
            conditions.append(
                "created_at < (SELECT created_at FROM workflow_runs WHERE run_id = ?)"
            )
            params.append(cursor)

        if query:
            conditions.append("(workflow_name LIKE ? OR input_kwargs LIKE ?)")
            search_param = f"%{query}%"
            params.extend([search_param, search_param])

        if status:
            conditions.append("status = ?")
            params.append(status.value)

        if start_time:
            conditions.append("created_at >= ?")
            params.append(start_time.isoformat())

        if end_time:
            conditions.append("created_at < ?")
            params.append(end_time.isoformat())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit + 1)  # Fetch one extra to determine if there are more

        sql = f"""
            SELECT * FROM workflow_runs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
        """

        async with db.execute(sql, tuple(params)) as db_cursor:
            rows = list(await db_cursor.fetchall())

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        runs = [self._row_to_workflow_run(row) for row in rows]
        next_cursor = runs[-1].run_id if runs and has_more else None

        return runs, next_cursor

    # Event Log Operations

    async def record_event(self, event: Event) -> None:
        """Record an event to the append-only event log."""
        db = self._ensure_connected()

        # Get next sequence number
        async with db.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 FROM events WHERE run_id = ?",
            (event.run_id,),
        ) as cursor:
            row = await cursor.fetchone()
            sequence = row[0] if row else 0

        await db.execute(
            """
            INSERT INTO events (event_id, run_id, sequence, type, timestamp, data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.run_id,
                sequence,
                event.type.value,
                event.timestamp.isoformat(),
                json.dumps(event.data),
            ),
        )
        await db.commit()

    async def get_events(
        self,
        run_id: str,
        event_types: list[str] | None = None,
    ) -> list[Event]:
        """Retrieve all events for a workflow run, ordered by sequence."""
        db = self._ensure_connected()

        if event_types:
            placeholders = ",".join("?" * len(event_types))
            sql = f"""
                SELECT * FROM events
                WHERE run_id = ? AND type IN ({placeholders})
                ORDER BY sequence ASC
            """
            params = [run_id] + event_types
        else:
            sql = "SELECT * FROM events WHERE run_id = ? ORDER BY sequence ASC"
            params = [run_id]

        async with db.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_event(row) for row in rows]

    async def get_latest_event(
        self,
        run_id: str,
        event_type: str | None = None,
    ) -> Event | None:
        """Get the latest event for a run, optionally filtered by type."""
        db = self._ensure_connected()

        if event_type:
            sql = """
                SELECT * FROM events
                WHERE run_id = ? AND type = ?
                ORDER BY sequence DESC
                LIMIT 1
            """
            params: tuple[str, ...] = (run_id, event_type)
        else:
            sql = """
                SELECT * FROM events
                WHERE run_id = ?
                ORDER BY sequence DESC
                LIMIT 1
            """
            params = (run_id,)

        async with db.execute(sql, params) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_event(row)

    # Step Operations

    async def create_step(self, step: StepExecution) -> None:
        """Create a step execution record."""
        db = self._ensure_connected()

        # Convert schema attempt (1-based) to DB retry_count (0-based)
        retry_count = step.attempt - 1 if step.attempt > 0 else 0

        await db.execute(
            """
            INSERT INTO steps (
                step_id, run_id, step_name, status, created_at, started_at,
                completed_at, input_args, input_kwargs, result, error, retry_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step.step_id,
                step.run_id,
                step.step_name,
                step.status.value,
                step.created_at.isoformat(),
                step.started_at.isoformat() if step.started_at else None,
                step.completed_at.isoformat() if step.completed_at else None,
                step.input_args,
                step.input_kwargs,
                step.result,
                step.error,
                retry_count,
            ),
        )
        await db.commit()

    async def get_step(self, step_id: str) -> StepExecution | None:
        """Retrieve a step execution by ID."""
        db = self._ensure_connected()

        async with db.execute("SELECT * FROM steps WHERE step_id = ?", (step_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_step_execution(row)

    async def update_step_status(
        self,
        step_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update step execution status."""
        db = self._ensure_connected()

        updates = ["status = ?"]
        params: list[Any] = [status]

        if result is not None:
            updates.append("result = ?")
            params.append(result)

        if error is not None:
            updates.append("error = ?")
            params.append(error)

        if status == "completed":
            updates.append("completed_at = ?")
            params.append(datetime.now(UTC).isoformat())

        params.append(step_id)

        await db.execute(
            f"UPDATE steps SET {', '.join(updates)} WHERE step_id = ?",
            tuple(params),
        )
        await db.commit()

    async def list_steps(self, run_id: str) -> list[StepExecution]:
        """List all steps for a workflow run."""
        db = self._ensure_connected()

        async with db.execute(
            "SELECT * FROM steps WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_step_execution(row) for row in rows]

    # Hook Operations

    async def create_hook(self, hook: Hook) -> None:
        """Create a hook record."""
        db = self._ensure_connected()

        await db.execute(
            """
            INSERT INTO hooks (
                hook_id, run_id, token, created_at, received_at, expires_at,
                status, payload, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hook.hook_id,
                hook.run_id,
                hook.token,
                hook.created_at.isoformat(),
                hook.received_at.isoformat() if hook.received_at else None,
                hook.expires_at.isoformat() if hook.expires_at else None,
                hook.status.value,
                hook.payload,
                json.dumps(hook.metadata),
            ),
        )
        await db.commit()

    async def get_hook(self, hook_id: str) -> Hook | None:
        """Retrieve a hook by ID."""
        db = self._ensure_connected()

        async with db.execute("SELECT * FROM hooks WHERE hook_id = ?", (hook_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_hook(row)

    async def get_hook_by_token(self, token: str) -> Hook | None:
        """Retrieve a hook by its token."""
        db = self._ensure_connected()

        async with db.execute("SELECT * FROM hooks WHERE token = ?", (token,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_hook(row)

    async def update_hook_status(
        self,
        hook_id: str,
        status: HookStatus,
        payload: str | None = None,
    ) -> None:
        """Update hook status and optionally payload."""
        db = self._ensure_connected()

        updates = ["status = ?"]
        params: list[Any] = [status.value]

        if payload is not None:
            updates.append("payload = ?")
            params.append(payload)

        if status == HookStatus.RECEIVED:
            updates.append("received_at = ?")
            params.append(datetime.now(UTC).isoformat())

        params.append(hook_id)

        await db.execute(
            f"UPDATE hooks SET {', '.join(updates)} WHERE hook_id = ?",
            tuple(params),
        )
        await db.commit()

    async def list_hooks(
        self,
        run_id: str | None = None,
        status: HookStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Hook]:
        """List hooks with optional filtering."""
        db = self._ensure_connected()

        conditions = []
        params: list[Any] = []

        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        if status:
            conditions.append("status = ?")
            params.append(status.value)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        sql = f"""
            SELECT * FROM hooks
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """

        async with db.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_hook(row) for row in rows]

    # Cancellation Flag Operations

    async def set_cancellation_flag(self, run_id: str) -> None:
        """Set a cancellation flag for a workflow run."""
        db = self._ensure_connected()

        await db.execute(
            """
            INSERT OR IGNORE INTO cancellation_flags (run_id, created_at)
            VALUES (?, ?)
            """,
            (run_id, datetime.now(UTC).isoformat()),
        )
        await db.commit()

    async def check_cancellation_flag(self, run_id: str) -> bool:
        """Check if a cancellation flag is set for a workflow run."""
        db = self._ensure_connected()

        async with db.execute(
            "SELECT 1 FROM cancellation_flags WHERE run_id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()

        return row is not None

    async def clear_cancellation_flag(self, run_id: str) -> None:
        """Clear the cancellation flag for a workflow run."""
        db = self._ensure_connected()

        await db.execute("DELETE FROM cancellation_flags WHERE run_id = ?", (run_id,))
        await db.commit()

    # Continue-As-New Chain Operations

    async def update_run_continuation(
        self,
        run_id: str,
        continued_to_run_id: str,
    ) -> None:
        """Update the continuation link for a workflow run."""
        db = self._ensure_connected()

        await db.execute(
            """
            UPDATE workflow_runs
            SET continued_to_run_id = ?, updated_at = ?
            WHERE run_id = ?
            """,
            (continued_to_run_id, datetime.now(UTC).isoformat(), run_id),
        )
        await db.commit()

    async def get_workflow_chain(
        self,
        run_id: str,
    ) -> list[WorkflowRun]:
        """Get all runs in a continue-as-new chain."""
        db = self._ensure_connected()

        # Find the first run in the chain
        current_id: str | None = run_id
        while True:
            async with db.execute(
                "SELECT continued_from_run_id FROM workflow_runs WHERE run_id = ?",
                (current_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if not row or not row[0]:
                break

            current_id = row[0]

        # Now collect all runs in the chain from first to last
        runs = []
        while current_id:
            run = await self.get_run(current_id)
            if not run:
                break
            runs.append(run)
            current_id = run.continued_to_run_id

        return runs

    # Child Workflow Operations

    async def get_children(
        self,
        parent_run_id: str,
        status: RunStatus | None = None,
    ) -> list[WorkflowRun]:
        """Get all child workflow runs for a parent workflow."""
        db = self._ensure_connected()

        if status:
            sql = """
                SELECT * FROM workflow_runs
                WHERE parent_run_id = ? AND status = ?
                ORDER BY created_at ASC
            """
            params: tuple[str, ...] = (parent_run_id, status.value)
        else:
            sql = """
                SELECT * FROM workflow_runs
                WHERE parent_run_id = ?
                ORDER BY created_at ASC
            """
            params = (parent_run_id,)

        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_workflow_run(row) for row in rows]

    async def get_parent(self, run_id: str) -> WorkflowRun | None:
        """Get the parent workflow run for a child workflow."""
        run = await self.get_run(run_id)
        if not run or not run.parent_run_id:
            return None

        return await self.get_run(run.parent_run_id)

    async def get_nesting_depth(self, run_id: str) -> int:
        """Get the nesting depth for a workflow."""
        run = await self.get_run(run_id)
        return run.nesting_depth if run else 0

    # Schedule Operations

    async def create_schedule(self, schedule: Schedule) -> None:
        """Create a new schedule record."""
        db = self._ensure_connected()

        # Extract spec components from the nested ScheduleSpec
        spec_value = schedule.spec.cron or schedule.spec.interval or ""
        spec_type = "cron" if schedule.spec.cron else "interval"
        timezone = schedule.spec.timezone

        await db.execute(
            """
            INSERT INTO schedules (
                schedule_id, workflow_name, spec, spec_type, timezone,
                input_args, input_kwargs, status, overlap_policy,
                next_run_time, last_run_time, running_run_ids, metadata,
                created_at, updated_at, paused_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                schedule.schedule_id,
                schedule.workflow_name,
                spec_value,
                spec_type,
                timezone,
                schedule.args,
                schedule.kwargs,
                schedule.status.value,
                schedule.overlap_policy.value,
                schedule.next_run_time.isoformat() if schedule.next_run_time else None,
                schedule.last_run_at.isoformat() if schedule.last_run_at else None,
                json.dumps(schedule.running_run_ids),
                json.dumps({}),  # metadata not in schema, store empty
                schedule.created_at.isoformat(),
                schedule.updated_at.isoformat()
                if schedule.updated_at
                else datetime.now(UTC).isoformat(),
                None,  # paused_at - derived from status
                None,  # deleted_at - derived from status
            ),
        )
        await db.commit()

    async def get_schedule(self, schedule_id: str) -> Schedule | None:
        """Retrieve a schedule by ID."""
        db = self._ensure_connected()

        async with db.execute(
            "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_schedule(row)

    async def update_schedule(self, schedule: Schedule) -> None:
        """Update an existing schedule."""
        db = self._ensure_connected()

        # Extract spec components from the nested ScheduleSpec
        spec_value = schedule.spec.cron or schedule.spec.interval or ""
        spec_type = "cron" if schedule.spec.cron else "interval"
        timezone = schedule.spec.timezone

        # Determine paused_at and deleted_at from status
        now = datetime.now(UTC)
        paused_at = now if schedule.status == ScheduleStatus.PAUSED else None
        deleted_at = now if schedule.status == ScheduleStatus.DELETED else None

        await db.execute(
            """
            UPDATE schedules SET
                workflow_name = ?, spec = ?, spec_type = ?, timezone = ?,
                input_args = ?, input_kwargs = ?, status = ?, overlap_policy = ?,
                next_run_time = ?, last_run_time = ?, running_run_ids = ?,
                metadata = ?, updated_at = ?, paused_at = ?, deleted_at = ?
            WHERE schedule_id = ?
            """,
            (
                schedule.workflow_name,
                spec_value,
                spec_type,
                timezone,
                schedule.args,
                schedule.kwargs,
                schedule.status.value,
                schedule.overlap_policy.value,
                schedule.next_run_time.isoformat() if schedule.next_run_time else None,
                schedule.last_run_at.isoformat() if schedule.last_run_at else None,
                json.dumps(schedule.running_run_ids),
                json.dumps({}),  # metadata not in schema, store empty
                schedule.updated_at.isoformat() if schedule.updated_at else now.isoformat(),
                paused_at.isoformat() if paused_at else None,
                deleted_at.isoformat() if deleted_at else None,
                schedule.schedule_id,
            ),
        )
        await db.commit()

    async def delete_schedule(self, schedule_id: str) -> None:
        """Mark a schedule as deleted (soft delete)."""
        db = self._ensure_connected()

        now = datetime.now(UTC)
        await db.execute(
            """
            UPDATE schedules
            SET status = ?, deleted_at = ?, updated_at = ?
            WHERE schedule_id = ?
            """,
            (ScheduleStatus.DELETED.value, now.isoformat(), now.isoformat(), schedule_id),
        )
        await db.commit()

    async def list_schedules(
        self,
        workflow_name: str | None = None,
        status: ScheduleStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Schedule]:
        """List schedules with optional filtering."""
        db = self._ensure_connected()

        conditions = []
        params: list[Any] = []

        if workflow_name:
            conditions.append("workflow_name = ?")
            params.append(workflow_name)

        if status:
            conditions.append("status = ?")
            params.append(status.value)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        sql = f"""
            SELECT * FROM schedules
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """

        async with db.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_schedule(row) for row in rows]

    async def get_due_schedules(self, now: datetime) -> list[Schedule]:
        """Get all schedules that are due to run."""
        db = self._ensure_connected()

        async with db.execute(
            """
            SELECT * FROM schedules
            WHERE status = ? AND next_run_time IS NOT NULL AND next_run_time <= ?
            ORDER BY next_run_time ASC
            """,
            (ScheduleStatus.ACTIVE.value, now.isoformat()),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_schedule(row) for row in rows]

    async def add_running_run(self, schedule_id: str, run_id: str) -> None:
        """Add a run_id to the schedule's running_run_ids list."""
        schedule = await self.get_schedule(schedule_id)
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")

        if run_id not in schedule.running_run_ids:
            schedule.running_run_ids.append(run_id)
            schedule.updated_at = datetime.now(UTC)
            await self.update_schedule(schedule)

    async def remove_running_run(self, schedule_id: str, run_id: str) -> None:
        """Remove a run_id from the schedule's running_run_ids list."""
        schedule = await self.get_schedule(schedule_id)
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")

        if run_id in schedule.running_run_ids:
            schedule.running_run_ids.remove(run_id)
            schedule.updated_at = datetime.now(UTC)
            await self.update_schedule(schedule)

    # Helper methods for converting database rows to domain objects

    def _row_to_workflow_run(self, row: Any) -> WorkflowRun:
        """Convert database row to WorkflowRun object."""
        return WorkflowRun(
            run_id=row[0],
            workflow_name=row[1],
            status=RunStatus(row[2]),
            created_at=datetime.fromisoformat(row[3]),
            updated_at=datetime.fromisoformat(row[4]),
            started_at=datetime.fromisoformat(row[5]) if row[5] else None,
            completed_at=datetime.fromisoformat(row[6]) if row[6] else None,
            input_args=row[7],
            input_kwargs=row[8],
            result=row[9],
            error=row[10],
            idempotency_key=row[11],
            max_duration=row[12],
            context=json.loads(row[13]) if row[13] else {},
            recovery_attempts=row[14],
            max_recovery_attempts=row[15],
            recover_on_worker_loss=bool(row[16]),
            parent_run_id=row[17],
            nesting_depth=row[18],
            continued_from_run_id=row[19],
            continued_to_run_id=row[20],
        )

    def _row_to_event(self, row: Any) -> Event:
        """Convert database row to Event object."""
        return Event(
            event_id=row[0],
            run_id=row[1],
            sequence=row[2],
            type=EventType(row[3]),
            timestamp=datetime.fromisoformat(row[4]),
            data=json.loads(row[5]) if row[5] else {},
        )

    def _row_to_step_execution(self, row: Any) -> StepExecution:
        """Convert database row to StepExecution object."""
        from pyworkflow.storage.schemas import StepStatus

        # Map DB retry_count (0-based) to schema attempt (1-based)
        retry_count = row[11] if row[11] is not None else 0
        return StepExecution(
            step_id=row[0],
            run_id=row[1],
            step_name=row[2],
            status=StepStatus(row[3]),
            created_at=datetime.fromisoformat(row[4]),
            started_at=datetime.fromisoformat(row[5]) if row[5] else None,
            completed_at=datetime.fromisoformat(row[6]) if row[6] else None,
            input_args=row[7],
            input_kwargs=row[8],
            result=row[9],
            error=row[10],
            attempt=retry_count + 1,
        )

    def _row_to_hook(self, row: Any) -> Hook:
        """Convert database row to Hook object."""
        return Hook(
            hook_id=row[0],
            run_id=row[1],
            token=row[2],
            created_at=datetime.fromisoformat(row[3]),
            received_at=datetime.fromisoformat(row[4]) if row[4] else None,
            expires_at=datetime.fromisoformat(row[5]) if row[5] else None,
            status=HookStatus(row[6]),
            payload=row[7],
            metadata=json.loads(row[8]) if row[8] else {},
        )

    def _row_to_schedule(self, row: Any) -> Schedule:
        """Convert database row to Schedule object."""
        # DB columns: schedule_id[0], workflow_name[1], spec[2], spec_type[3], timezone[4],
        # input_args[5], input_kwargs[6], status[7], overlap_policy[8], next_run_time[9],
        # last_run_time[10], running_run_ids[11], metadata[12], created_at[13], updated_at[14],
        # paused_at[15], deleted_at[16]

        # Reconstruct ScheduleSpec from flattened DB columns
        spec_value = row[2]
        spec_type = row[3]
        timezone = row[4] or "UTC"

        if spec_type == "cron":
            spec = ScheduleSpec(cron=spec_value, timezone=timezone)
        else:
            spec = ScheduleSpec(interval=spec_value, timezone=timezone)

        return Schedule(
            schedule_id=row[0],
            workflow_name=row[1],
            spec=spec,
            status=ScheduleStatus(row[7]),
            args=row[5] or "[]",
            kwargs=row[6] or "{}",
            overlap_policy=OverlapPolicy(row[8]),
            created_at=datetime.fromisoformat(row[13]),
            updated_at=datetime.fromisoformat(row[14]) if row[14] else None,
            last_run_at=datetime.fromisoformat(row[10]) if row[10] else None,
            next_run_time=datetime.fromisoformat(row[9]) if row[9] else None,
            running_run_ids=json.loads(row[11]) if row[11] else [],
        )
