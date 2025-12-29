"""
MySQL storage backend using aiomysql.

This backend stores workflow data in a MySQL database, suitable for:
- Production deployments requiring scalability
- Multi-instance deployments
- Teams familiar with MySQL/MariaDB

Provides ACID guarantees, connection pooling, and efficient querying with SQL indexes.
"""

import json
from datetime import UTC, datetime
from typing import Any

import aiomysql

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
    StepStatus,
    WorkflowRun,
)


class MySQLStorageBackend(StorageBackend):
    """
    MySQL storage backend using aiomysql for async operations.

    All workflow data is stored in a MySQL database with proper
    indexes for efficient querying and connection pooling for performance.
    """

    def __init__(
        self,
        dsn: str | None = None,
        host: str = "localhost",
        port: int = 3306,
        user: str = "pyworkflow",
        password: str = "",
        database: str = "pyworkflow",
        min_pool_size: int = 1,
        max_pool_size: int = 10,
    ):
        """
        Initialize MySQL storage backend.

        Args:
            dsn: Connection string (not commonly used with aiomysql)
            host: Database host (used if dsn not provided)
            port: Database port (used if dsn not provided)
            user: Database user (used if dsn not provided)
            password: Database password (used if dsn not provided)
            database: Database name (used if dsn not provided)
            min_pool_size: Minimum connections in pool
            max_pool_size: Maximum connections in pool
        """
        self.dsn = dsn
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self._pool: aiomysql.Pool | None = None
        self._initialized = False

    async def connect(self) -> None:
        """Initialize connection pool and create tables if needed."""
        if self._pool is None:
            self._pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                minsize=self.min_pool_size,
                maxsize=self.max_pool_size,
                autocommit=True,
            )

        if not self._initialized:
            await self._initialize_schema()
            self._initialized = True

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            self._initialized = False

    async def _initialize_schema(self) -> None:
        """Create database tables if they don't exist."""
        if not self._pool:
            await self.connect()

        pool = self._ensure_connected()
        async with pool.acquire() as conn, conn.cursor() as cur:
            # Workflow runs table
            await cur.execute("""
                    CREATE TABLE IF NOT EXISTS workflow_runs (
                        run_id VARCHAR(255) PRIMARY KEY,
                        workflow_name VARCHAR(255) NOT NULL,
                        status VARCHAR(50) NOT NULL,
                        created_at DATETIME(6) NOT NULL,
                        updated_at DATETIME(6) NOT NULL,
                        started_at DATETIME(6),
                        completed_at DATETIME(6),
                        input_args LONGTEXT NOT NULL DEFAULT '[]',
                        input_kwargs LONGTEXT NOT NULL DEFAULT '{}',
                        result LONGTEXT,
                        error LONGTEXT,
                        idempotency_key VARCHAR(255),
                        max_duration VARCHAR(255),
                        metadata LONGTEXT DEFAULT '{}',
                        recovery_attempts INT DEFAULT 0,
                        max_recovery_attempts INT DEFAULT 3,
                        recover_on_worker_loss BOOLEAN DEFAULT TRUE,
                        parent_run_id VARCHAR(255),
                        nesting_depth INT DEFAULT 0,
                        continued_from_run_id VARCHAR(255),
                        continued_to_run_id VARCHAR(255),
                        INDEX idx_runs_status (status),
                        INDEX idx_runs_workflow_name (workflow_name),
                        INDEX idx_runs_created_at (created_at DESC),
                        UNIQUE INDEX idx_runs_idempotency_key (idempotency_key),
                        INDEX idx_runs_parent_run_id (parent_run_id),
                        FOREIGN KEY (parent_run_id) REFERENCES workflow_runs(run_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

            # Events table
            await cur.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        event_id VARCHAR(255) PRIMARY KEY,
                        run_id VARCHAR(255) NOT NULL,
                        sequence INT NOT NULL,
                        type VARCHAR(100) NOT NULL,
                        timestamp DATETIME(6) NOT NULL,
                        data LONGTEXT NOT NULL DEFAULT '{}',
                        INDEX idx_events_run_id_sequence (run_id, sequence),
                        INDEX idx_events_type (type),
                        FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

            # Steps table
            await cur.execute("""
                    CREATE TABLE IF NOT EXISTS steps (
                        step_id VARCHAR(255) PRIMARY KEY,
                        run_id VARCHAR(255) NOT NULL,
                        step_name VARCHAR(255) NOT NULL,
                        status VARCHAR(50) NOT NULL,
                        created_at DATETIME(6) NOT NULL,
                        started_at DATETIME(6),
                        completed_at DATETIME(6),
                        input_args LONGTEXT NOT NULL DEFAULT '[]',
                        input_kwargs LONGTEXT NOT NULL DEFAULT '{}',
                        result LONGTEXT,
                        error LONGTEXT,
                        retry_count INT DEFAULT 0,
                        INDEX idx_steps_run_id (run_id),
                        FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

            # Hooks table
            await cur.execute("""
                    CREATE TABLE IF NOT EXISTS hooks (
                        hook_id VARCHAR(255) PRIMARY KEY,
                        run_id VARCHAR(255) NOT NULL,
                        token VARCHAR(255) UNIQUE NOT NULL,
                        created_at DATETIME(6) NOT NULL,
                        received_at DATETIME(6),
                        expires_at DATETIME(6),
                        status VARCHAR(50) NOT NULL,
                        payload LONGTEXT,
                        metadata LONGTEXT DEFAULT '{}',
                        UNIQUE INDEX idx_hooks_token (token),
                        INDEX idx_hooks_run_id (run_id),
                        INDEX idx_hooks_status (status),
                        FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

            # Schedules table
            await cur.execute("""
                    CREATE TABLE IF NOT EXISTS schedules (
                        schedule_id VARCHAR(255) PRIMARY KEY,
                        workflow_name VARCHAR(255) NOT NULL,
                        spec LONGTEXT NOT NULL,
                        spec_type VARCHAR(50) NOT NULL,
                        timezone VARCHAR(100),
                        input_args LONGTEXT NOT NULL DEFAULT '[]',
                        input_kwargs LONGTEXT NOT NULL DEFAULT '{}',
                        status VARCHAR(50) NOT NULL,
                        overlap_policy VARCHAR(50) NOT NULL,
                        next_run_time DATETIME(6),
                        last_run_time DATETIME(6),
                        running_run_ids LONGTEXT DEFAULT '[]',
                        metadata LONGTEXT DEFAULT '{}',
                        created_at DATETIME(6) NOT NULL,
                        updated_at DATETIME(6) NOT NULL,
                        paused_at DATETIME(6),
                        deleted_at DATETIME(6),
                        INDEX idx_schedules_status (status),
                        INDEX idx_schedules_next_run_time (next_run_time),
                        INDEX idx_schedules_workflow_name (workflow_name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

            # Cancellation flags table
            await cur.execute("""
                    CREATE TABLE IF NOT EXISTS cancellation_flags (
                        run_id VARCHAR(255) PRIMARY KEY,
                        created_at DATETIME(6) NOT NULL,
                        FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

    def _ensure_connected(self) -> aiomysql.Pool:
        """Ensure database pool is connected."""
        if not self._pool:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._pool

    # Workflow Run Operations

    async def create_run(self, run: WorkflowRun) -> None:
        """Create a new workflow run record."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, workflow_name, status, created_at, updated_at, started_at,
                    completed_at, input_args, input_kwargs, result, error, idempotency_key,
                    max_duration, metadata, recovery_attempts, max_recovery_attempts,
                    recover_on_worker_loss, parent_run_id, nesting_depth,
                    continued_from_run_id, continued_to_run_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run.run_id,
                    run.workflow_name,
                    run.status.value,
                    run.created_at,
                    run.updated_at,
                    run.started_at,
                    run.completed_at,
                    run.input_args,
                    run.input_kwargs,
                    run.result,
                    run.error,
                    run.idempotency_key,
                    run.max_duration,
                    json.dumps(run.context),
                    run.recovery_attempts,
                    run.max_recovery_attempts,
                    run.recover_on_worker_loss,
                    run.parent_run_id,
                    run.nesting_depth,
                    run.continued_from_run_id,
                    run.continued_to_run_id,
                ),
            )

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        """Retrieve a workflow run by ID."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM workflow_runs WHERE run_id = %s", (run_id,))
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_workflow_run(row)

    async def get_run_by_idempotency_key(self, key: str) -> WorkflowRun | None:
        """Retrieve a workflow run by idempotency key."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM workflow_runs WHERE idempotency_key = %s", (key,))
            row = await cur.fetchone()

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
        pool = self._ensure_connected()

        now = datetime.now(UTC)
        completed_at = now if status == RunStatus.COMPLETED else None

        # Build dynamic query
        updates = ["status = %s", "updated_at = %s"]
        params: list[Any] = [status.value, now]

        if result is not None:
            updates.append("result = %s")
            params.append(result)

        if error is not None:
            updates.append("error = %s")
            params.append(error)

        if completed_at:
            updates.append("completed_at = %s")
            params.append(completed_at)

        params.append(run_id)

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                f"UPDATE workflow_runs SET {', '.join(updates)} WHERE run_id = %s",
                tuple(params),
            )

    async def update_run_recovery_attempts(
        self,
        run_id: str,
        recovery_attempts: int,
    ) -> None:
        """Update the recovery attempts counter for a workflow run."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    UPDATE workflow_runs
                    SET recovery_attempts = %s, updated_at = %s
                    WHERE run_id = %s
                    """,
                (recovery_attempts, datetime.now(UTC), run_id),
            )

    async def update_run_context(
        self,
        run_id: str,
        context: dict,
    ) -> None:
        """Update the step context for a workflow run."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    UPDATE workflow_runs
                    SET metadata = %s, updated_at = %s
                    WHERE run_id = %s
                    """,
                (json.dumps(context), datetime.now(UTC), run_id),
            )

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
        pool = self._ensure_connected()

        conditions = []
        params: list[Any] = []

        if cursor:
            conditions.append(
                "created_at < (SELECT created_at FROM workflow_runs WHERE run_id = %s)"
            )
            params.append(cursor)

        if query:
            conditions.append("(workflow_name LIKE %s OR input_kwargs LIKE %s)")
            search_param = f"%{query}%"
            params.extend([search_param, search_param])

        if status:
            conditions.append("status = %s")
            params.append(status.value)

        if start_time:
            conditions.append("created_at >= %s")
            params.append(start_time)

        if end_time:
            conditions.append("created_at < %s")
            params.append(end_time)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit + 1)  # Fetch one extra to determine if there are more

        sql = f"""
            SELECT * FROM workflow_runs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
        """

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, tuple(params))
            rows = await cur.fetchall()

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        runs = [self._row_to_workflow_run(row) for row in rows]
        next_cursor = runs[-1].run_id if runs and has_more else None

        return runs, next_cursor

    # Event Log Operations

    async def record_event(self, event: Event) -> None:
        """Record an event to the append-only event log."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn:
            # Use transaction for atomic sequence assignment
            await conn.begin()
            try:
                async with conn.cursor() as cur:
                    # Get next sequence number
                    await cur.execute(
                        "SELECT COALESCE(MAX(sequence), -1) + 1 FROM events WHERE run_id = %s",
                        (event.run_id,),
                    )
                    row = await cur.fetchone()
                    sequence = row[0] if row else 0

                    await cur.execute(
                        """
                        INSERT INTO events (event_id, run_id, sequence, type, timestamp, data)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            event.event_id,
                            event.run_id,
                            sequence,
                            event.type.value,
                            event.timestamp,
                            json.dumps(event.data),
                        ),
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def get_events(
        self,
        run_id: str,
        event_types: list[str] | None = None,
    ) -> list[Event]:
        """Retrieve all events for a workflow run, ordered by sequence."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            if event_types:
                placeholders = ", ".join(["%s"] * len(event_types))
                await cur.execute(
                    f"""
                        SELECT * FROM events
                        WHERE run_id = %s AND type IN ({placeholders})
                        ORDER BY sequence ASC
                        """,
                    (run_id, *event_types),
                )
            else:
                await cur.execute(
                    "SELECT * FROM events WHERE run_id = %s ORDER BY sequence ASC",
                    (run_id,),
                )
            rows = await cur.fetchall()

        return [self._row_to_event(row) for row in rows]

    async def get_latest_event(
        self,
        run_id: str,
        event_type: str | None = None,
    ) -> Event | None:
        """Get the latest event for a run, optionally filtered by type."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            if event_type:
                await cur.execute(
                    """
                        SELECT * FROM events
                        WHERE run_id = %s AND type = %s
                        ORDER BY sequence DESC
                        LIMIT 1
                        """,
                    (run_id, event_type),
                )
            else:
                await cur.execute(
                    """
                        SELECT * FROM events
                        WHERE run_id = %s
                        ORDER BY sequence DESC
                        LIMIT 1
                        """,
                    (run_id,),
                )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_event(row)

    # Step Operations

    async def create_step(self, step: StepExecution) -> None:
        """Create a step execution record."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    INSERT INTO steps (
                        step_id, run_id, step_name, status, created_at, started_at,
                        completed_at, input_args, input_kwargs, result, error, retry_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                (
                    step.step_id,
                    step.run_id,
                    step.step_name,
                    step.status.value,
                    step.created_at,
                    step.started_at,
                    step.completed_at,
                    step.input_args,
                    step.input_kwargs,
                    step.result,
                    step.error,
                    step.attempt,
                ),
            )

    async def get_step(self, step_id: str) -> StepExecution | None:
        """Retrieve a step execution by ID."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM steps WHERE step_id = %s", (step_id,))
            row = await cur.fetchone()

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
        pool = self._ensure_connected()

        updates = ["status = %s"]
        params: list[Any] = [status]

        if result is not None:
            updates.append("result = %s")
            params.append(result)

        if error is not None:
            updates.append("error = %s")
            params.append(error)

        if status == "completed":
            updates.append("completed_at = %s")
            params.append(datetime.now(UTC))

        params.append(step_id)

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                f"UPDATE steps SET {', '.join(updates)} WHERE step_id = %s",
                tuple(params),
            )

    async def list_steps(self, run_id: str) -> list[StepExecution]:
        """List all steps for a workflow run."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM steps WHERE run_id = %s ORDER BY created_at ASC",
                (run_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_step_execution(row) for row in rows]

    # Hook Operations

    async def create_hook(self, hook: Hook) -> None:
        """Create a hook record."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    INSERT INTO hooks (
                        hook_id, run_id, token, created_at, received_at, expires_at,
                        status, payload, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                (
                    hook.hook_id,
                    hook.run_id,
                    hook.token,
                    hook.created_at,
                    hook.received_at,
                    hook.expires_at,
                    hook.status.value,
                    hook.payload,
                    json.dumps(hook.metadata),
                ),
            )

    async def get_hook(self, hook_id: str) -> Hook | None:
        """Retrieve a hook by ID."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM hooks WHERE hook_id = %s", (hook_id,))
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_hook(row)

    async def get_hook_by_token(self, token: str) -> Hook | None:
        """Retrieve a hook by its token."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM hooks WHERE token = %s", (token,))
            row = await cur.fetchone()

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
        pool = self._ensure_connected()

        updates = ["status = %s"]
        params: list[Any] = [status.value]

        if payload is not None:
            updates.append("payload = %s")
            params.append(payload)

        if status == HookStatus.RECEIVED:
            updates.append("received_at = %s")
            params.append(datetime.now(UTC))

        params.append(hook_id)

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                f"UPDATE hooks SET {', '.join(updates)} WHERE hook_id = %s",
                tuple(params),
            )

    async def list_hooks(
        self,
        run_id: str | None = None,
        status: HookStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Hook]:
        """List hooks with optional filtering."""
        pool = self._ensure_connected()

        conditions = []
        params: list[Any] = []

        if run_id:
            conditions.append("run_id = %s")
            params.append(run_id)

        if status:
            conditions.append("status = %s")
            params.append(status.value)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        sql = f"""
            SELECT * FROM hooks
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, tuple(params))
            rows = await cur.fetchall()

        return [self._row_to_hook(row) for row in rows]

    # Cancellation Flag Operations

    async def set_cancellation_flag(self, run_id: str) -> None:
        """Set a cancellation flag for a workflow run."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    INSERT IGNORE INTO cancellation_flags (run_id, created_at)
                    VALUES (%s, %s)
                    """,
                (run_id, datetime.now(UTC)),
            )

    async def check_cancellation_flag(self, run_id: str) -> bool:
        """Check if a cancellation flag is set for a workflow run."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM cancellation_flags WHERE run_id = %s", (run_id,))
            row = await cur.fetchone()

        return row is not None

    async def clear_cancellation_flag(self, run_id: str) -> None:
        """Clear the cancellation flag for a workflow run."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM cancellation_flags WHERE run_id = %s", (run_id,))

    # Continue-As-New Chain Operations

    async def update_run_continuation(
        self,
        run_id: str,
        continued_to_run_id: str,
    ) -> None:
        """Update the continuation link for a workflow run."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    UPDATE workflow_runs
                    SET continued_to_run_id = %s, updated_at = %s
                    WHERE run_id = %s
                    """,
                (continued_to_run_id, datetime.now(UTC), run_id),
            )

    async def get_workflow_chain(
        self,
        run_id: str,
    ) -> list[WorkflowRun]:
        """Get all runs in a continue-as-new chain."""
        pool = self._ensure_connected()

        # Find the first run in the chain
        current_id: str | None = run_id
        async with pool.acquire() as conn, conn.cursor() as cur:
            while True:
                await cur.execute(
                    "SELECT continued_from_run_id FROM workflow_runs WHERE run_id = %s",
                    (current_id,),
                )
                row = await cur.fetchone()

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
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            if status:
                await cur.execute(
                    """
                        SELECT * FROM workflow_runs
                        WHERE parent_run_id = %s AND status = %s
                        ORDER BY created_at ASC
                        """,
                    (parent_run_id, status.value),
                )
            else:
                await cur.execute(
                    """
                        SELECT * FROM workflow_runs
                        WHERE parent_run_id = %s
                        ORDER BY created_at ASC
                        """,
                    (parent_run_id,),
                )
            rows = await cur.fetchall()

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
        pool = self._ensure_connected()

        # Derive spec_type from the ScheduleSpec
        spec_type = (
            "cron" if schedule.spec.cron else ("interval" if schedule.spec.interval else "calendar")
        )

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    INSERT INTO schedules (
                        schedule_id, workflow_name, spec, spec_type, timezone,
                        input_args, input_kwargs, status, overlap_policy,
                        next_run_time, last_run_time, running_run_ids, metadata,
                        created_at, updated_at, paused_at, deleted_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                (
                    schedule.schedule_id,
                    schedule.workflow_name,
                    json.dumps(schedule.spec.to_dict()),
                    spec_type,
                    schedule.spec.timezone,
                    schedule.args,
                    schedule.kwargs,
                    schedule.status.value,
                    schedule.overlap_policy.value,
                    schedule.next_run_time,
                    schedule.last_run_at,
                    json.dumps(schedule.running_run_ids),
                    "{}",  # metadata - not in current dataclass
                    schedule.created_at,
                    schedule.updated_at,
                    None,  # paused_at - not in current dataclass
                    None,  # deleted_at - not in current dataclass
                ),
            )

    async def get_schedule(self, schedule_id: str) -> Schedule | None:
        """Retrieve a schedule by ID."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM schedules WHERE schedule_id = %s", (schedule_id,))
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_schedule(row)

    async def update_schedule(self, schedule: Schedule) -> None:
        """Update an existing schedule."""
        pool = self._ensure_connected()

        # Derive spec_type from the ScheduleSpec
        spec_type = (
            "cron" if schedule.spec.cron else ("interval" if schedule.spec.interval else "calendar")
        )

        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    UPDATE schedules SET
                        workflow_name = %s, spec = %s, spec_type = %s, timezone = %s,
                        input_args = %s, input_kwargs = %s, status = %s, overlap_policy = %s,
                        next_run_time = %s, last_run_time = %s, running_run_ids = %s,
                        metadata = %s, updated_at = %s, paused_at = %s, deleted_at = %s
                    WHERE schedule_id = %s
                    """,
                (
                    schedule.workflow_name,
                    json.dumps(schedule.spec.to_dict()),
                    spec_type,
                    schedule.spec.timezone,
                    schedule.args,
                    schedule.kwargs,
                    schedule.status.value,
                    schedule.overlap_policy.value,
                    schedule.next_run_time,
                    schedule.last_run_at,
                    json.dumps(schedule.running_run_ids),
                    "{}",  # metadata - not in current dataclass
                    schedule.updated_at,
                    None,  # paused_at - not in current dataclass
                    None,  # deleted_at - not in current dataclass
                    schedule.schedule_id,
                ),
            )

    async def delete_schedule(self, schedule_id: str) -> None:
        """Mark a schedule as deleted (soft delete)."""
        pool = self._ensure_connected()

        now = datetime.now(UTC)
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    UPDATE schedules
                    SET status = %s, deleted_at = %s, updated_at = %s
                    WHERE schedule_id = %s
                    """,
                (ScheduleStatus.DELETED.value, now, now, schedule_id),
            )

    async def list_schedules(
        self,
        workflow_name: str | None = None,
        status: ScheduleStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Schedule]:
        """List schedules with optional filtering."""
        pool = self._ensure_connected()

        conditions = []
        params: list[Any] = []

        if workflow_name:
            conditions.append("workflow_name = %s")
            params.append(workflow_name)

        if status:
            conditions.append("status = %s")
            params.append(status.value)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        sql = f"""
            SELECT * FROM schedules
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, tuple(params))
            rows = await cur.fetchall()

        return [self._row_to_schedule(row) for row in rows]

    async def get_due_schedules(self, now: datetime) -> list[Schedule]:
        """Get all schedules that are due to run."""
        pool = self._ensure_connected()

        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """
                    SELECT * FROM schedules
                    WHERE status = %s AND next_run_time IS NOT NULL AND next_run_time <= %s
                    ORDER BY next_run_time ASC
                    """,
                (ScheduleStatus.ACTIVE.value, now),
            )
            rows = await cur.fetchall()

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

    def _row_to_workflow_run(self, row: dict) -> WorkflowRun:
        """Convert database row to WorkflowRun object."""
        return WorkflowRun(
            run_id=row["run_id"],
            workflow_name=row["workflow_name"],
            status=RunStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            input_args=row["input_args"],
            input_kwargs=row["input_kwargs"],
            result=row["result"],
            error=row["error"],
            idempotency_key=row["idempotency_key"],
            max_duration=row["max_duration"],
            context=json.loads(row["metadata"]) if row["metadata"] else {},
            recovery_attempts=row["recovery_attempts"],
            max_recovery_attempts=row["max_recovery_attempts"],
            recover_on_worker_loss=bool(row["recover_on_worker_loss"]),
            parent_run_id=row["parent_run_id"],
            nesting_depth=row["nesting_depth"],
            continued_from_run_id=row["continued_from_run_id"],
            continued_to_run_id=row["continued_to_run_id"],
        )

    def _row_to_event(self, row: dict) -> Event:
        """Convert database row to Event object."""
        return Event(
            event_id=row["event_id"],
            run_id=row["run_id"],
            sequence=row["sequence"],
            type=EventType(row["type"]),
            timestamp=row["timestamp"],
            data=json.loads(row["data"]) if row["data"] else {},
        )

    def _row_to_step_execution(self, row: dict) -> StepExecution:
        """Convert database row to StepExecution object."""
        return StepExecution(
            step_id=row["step_id"],
            run_id=row["run_id"],
            step_name=row["step_name"],
            status=StepStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            input_args=row["input_args"],
            input_kwargs=row["input_kwargs"],
            result=row["result"],
            error=row["error"],
            attempt=row["retry_count"] or 1,
        )

    def _row_to_hook(self, row: dict) -> Hook:
        """Convert database row to Hook object."""
        return Hook(
            hook_id=row["hook_id"],
            run_id=row["run_id"],
            token=row["token"],
            created_at=row["created_at"],
            received_at=row["received_at"],
            expires_at=row["expires_at"],
            status=HookStatus(row["status"]),
            payload=row["payload"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def _row_to_schedule(self, row: dict) -> Schedule:
        """Convert database row to Schedule object."""
        # Parse the spec from JSON and create ScheduleSpec
        spec_data = json.loads(row["spec"]) if row["spec"] else {}
        spec = ScheduleSpec.from_dict(spec_data)

        return Schedule(
            schedule_id=row["schedule_id"],
            workflow_name=row["workflow_name"],
            spec=spec,
            status=ScheduleStatus(row["status"]),
            args=row["input_args"],
            kwargs=row["input_kwargs"],
            overlap_policy=OverlapPolicy(row["overlap_policy"]),
            next_run_time=row["next_run_time"],
            last_run_at=row["last_run_time"],
            running_run_ids=json.loads(row["running_run_ids"]) if row["running_run_ids"] else [],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
