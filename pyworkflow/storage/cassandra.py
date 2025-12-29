"""
Apache Cassandra storage backend using cassandra-driver.

This backend stores workflow data in Cassandra, suitable for:
- Massive horizontal scalability (petabyte-scale)
- High availability with no single point of failure
- Multi-datacenter replication
- High write throughput (optimized for event sourcing)

Uses a multi-table design with denormalized data for efficient queries
without ALLOW FILTERING.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from cassandra import ConsistencyLevel
from cassandra.auth import PlainTextAuthProvider
from cassandra.cluster import Cluster, Session
from cassandra.query import BatchStatement, SimpleStatement

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


class CassandraStorageBackend(StorageBackend):
    """
    Apache Cassandra storage backend.

    Uses a multi-table design with denormalized data for efficient queries.
    Each table is optimized for specific query patterns, avoiding the need
    for ALLOW FILTERING.

    Tables:
    - Primary tables: workflow_runs, events, steps, hooks, schedules, cancellation_flags
    - Lookup tables: steps_by_id, hooks_by_id, hooks_by_token, runs_by_idempotency_key
    - Query tables: runs_by_status, runs_by_workflow, runs_by_parent, schedules_by_workflow,
                    schedules_by_status, due_schedules

    Events use TIMEUUID for natural time-based ordering.
    List queries use time-bucketed partitions to avoid hot partitions.
    """

    def __init__(
        self,
        contact_points: list[str] | None = None,
        port: int = 9042,
        keyspace: str = "pyworkflow",
        username: str | None = None,
        password: str | None = None,
        read_consistency: str = "LOCAL_QUORUM",
        write_consistency: str = "LOCAL_QUORUM",
        replication_strategy: str = "SimpleStrategy",
        replication_factor: int = 3,
        datacenter: str | None = None,
        protocol_version: int = 4,
        connect_timeout: float = 10.0,
    ):
        """
        Initialize Cassandra storage backend.

        Args:
            contact_points: List of Cassandra node addresses (default: ["localhost"])
            port: Cassandra native transport port (default: 9042)
            keyspace: Keyspace name (default: "pyworkflow")
            username: Optional authentication username
            password: Optional authentication password
            read_consistency: Read consistency level (default: "LOCAL_QUORUM")
            write_consistency: Write consistency level (default: "LOCAL_QUORUM")
            replication_strategy: Keyspace replication strategy (default: "SimpleStrategy")
            replication_factor: Replication factor for SimpleStrategy (default: 3)
            datacenter: Datacenter name for NetworkTopologyStrategy
            protocol_version: CQL protocol version (default: 4)
            connect_timeout: Connection timeout in seconds (default: 10.0)
        """
        self.contact_points = contact_points or ["localhost"]
        self.port = port
        self.keyspace = keyspace
        self.username = username
        self.password = password
        self.read_consistency = getattr(ConsistencyLevel, read_consistency)
        self.write_consistency = getattr(ConsistencyLevel, write_consistency)
        self.replication_strategy = replication_strategy
        self.replication_factor = replication_factor
        self.datacenter = datacenter
        self.protocol_version = protocol_version
        self.connect_timeout = connect_timeout

        self._cluster: Cluster | None = None
        self._session: Session | None = None
        self._initialized = False

    async def connect(self) -> None:
        """Initialize connection and create keyspace/tables if needed."""
        if self._session is None:
            auth_provider = None
            if self.username and self.password:
                auth_provider = PlainTextAuthProvider(
                    username=self.username, password=self.password
                )

            self._cluster = Cluster(
                contact_points=self.contact_points,
                port=self.port,
                auth_provider=auth_provider,
                protocol_version=self.protocol_version,
                connect_timeout=self.connect_timeout,
            )
            self._session = self._cluster.connect()

        if not self._initialized:
            await self._initialize_schema()
            self._initialized = True

    async def disconnect(self) -> None:
        """Close connection to Cassandra cluster."""
        if self._session:
            self._session.shutdown()
            self._session = None
        if self._cluster:
            self._cluster.shutdown()
            self._cluster = None
        self._initialized = False

    async def health_check(self) -> bool:
        """Check if Cassandra cluster is healthy and accessible."""
        try:
            if not self._session:
                return False
            self._session.execute("SELECT now() FROM system.local")
            return True
        except Exception:
            return False

    def _ensure_connected(self) -> Session:
        """Ensure Cassandra session is connected."""
        if not self._session:
            raise RuntimeError("Cassandra not connected. Call connect() first.")
        return self._session

    async def _initialize_schema(self) -> None:
        """Create keyspace and tables if they don't exist."""
        session = self._ensure_connected()

        # Create keyspace
        if self.replication_strategy == "NetworkTopologyStrategy" and self.datacenter:
            replication = (
                f"{{'class': 'NetworkTopologyStrategy', "
                f"'{self.datacenter}': {self.replication_factor}}}"
            )
        else:
            replication = (
                f"{{'class': 'SimpleStrategy', 'replication_factor': {self.replication_factor}}}"
            )

        session.execute(
            f"CREATE KEYSPACE IF NOT EXISTS {self.keyspace} WITH replication = {replication}"
        )
        session.set_keyspace(self.keyspace)

        # Create primary tables
        await self._create_workflow_runs_table(session)
        await self._create_events_table(session)
        await self._create_steps_tables(session)
        await self._create_hooks_tables(session)
        await self._create_cancellation_flags_table(session)
        await self._create_schedules_tables(session)

        # Create query pattern tables
        await self._create_runs_query_tables(session)

    async def _create_workflow_runs_table(self, session: Session) -> None:
        """Create workflow_runs primary table and lookup tables."""
        session.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id TEXT PRIMARY KEY,
                workflow_name TEXT,
                status TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                input_args TEXT,
                input_kwargs TEXT,
                result TEXT,
                error TEXT,
                idempotency_key TEXT,
                max_duration TEXT,
                context TEXT,
                recovery_attempts INT,
                max_recovery_attempts INT,
                recover_on_worker_loss BOOLEAN,
                parent_run_id TEXT,
                nesting_depth INT,
                continued_from_run_id TEXT,
                continued_to_run_id TEXT
            )
        """)

        # Idempotency key lookup table
        session.execute("""
            CREATE TABLE IF NOT EXISTS runs_by_idempotency_key (
                idempotency_key TEXT PRIMARY KEY,
                run_id TEXT
            )
        """)

    async def _create_events_table(self, session: Session) -> None:
        """Create events table with TIMEUUID ordering."""
        session.execute("""
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT,
                event_time TIMEUUID,
                event_id TEXT,
                type TEXT,
                timestamp TIMESTAMP,
                data TEXT,
                PRIMARY KEY (run_id, event_time)
            ) WITH CLUSTERING ORDER BY (event_time ASC)
        """)

    async def _create_steps_tables(self, session: Session) -> None:
        """Create steps tables."""
        # Steps by run
        session.execute("""
            CREATE TABLE IF NOT EXISTS steps (
                run_id TEXT,
                step_id TEXT,
                step_name TEXT,
                status TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                input_args TEXT,
                input_kwargs TEXT,
                result TEXT,
                error TEXT,
                attempt INT,
                max_retries INT,
                retry_after TIMESTAMP,
                retry_delay TEXT,
                PRIMARY KEY (run_id, step_id)
            )
        """)

        # Step lookup by ID
        session.execute("""
            CREATE TABLE IF NOT EXISTS steps_by_id (
                step_id TEXT PRIMARY KEY,
                run_id TEXT
            )
        """)

    async def _create_hooks_tables(self, session: Session) -> None:
        """Create hooks tables."""
        # Hooks by run
        session.execute("""
            CREATE TABLE IF NOT EXISTS hooks (
                run_id TEXT,
                hook_id TEXT,
                token TEXT,
                url TEXT,
                status TEXT,
                created_at TIMESTAMP,
                received_at TIMESTAMP,
                expires_at TIMESTAMP,
                payload TEXT,
                name TEXT,
                payload_schema TEXT,
                metadata TEXT,
                PRIMARY KEY (run_id, hook_id)
            )
        """)

        # Hook lookup by ID
        session.execute("""
            CREATE TABLE IF NOT EXISTS hooks_by_id (
                hook_id TEXT PRIMARY KEY,
                run_id TEXT
            )
        """)

        # Hook lookup by token
        session.execute("""
            CREATE TABLE IF NOT EXISTS hooks_by_token (
                token TEXT PRIMARY KEY,
                run_id TEXT,
                hook_id TEXT
            )
        """)

    async def _create_cancellation_flags_table(self, session: Session) -> None:
        """Create cancellation flags table."""
        session.execute("""
            CREATE TABLE IF NOT EXISTS cancellation_flags (
                run_id TEXT PRIMARY KEY,
                created_at TIMESTAMP
            )
        """)

    async def _create_schedules_tables(self, session: Session) -> None:
        """Create schedules tables."""
        # Main schedules table
        session.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                schedule_id TEXT PRIMARY KEY,
                workflow_name TEXT,
                spec TEXT,
                spec_type TEXT,
                timezone TEXT,
                args TEXT,
                kwargs TEXT,
                status TEXT,
                overlap_policy TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                last_run_at TIMESTAMP,
                next_run_time TIMESTAMP,
                last_run_id TEXT,
                running_run_ids TEXT,
                buffered_count INT
            )
        """)

        # Schedules by workflow
        session.execute("""
            CREATE TABLE IF NOT EXISTS schedules_by_workflow (
                workflow_name TEXT,
                schedule_id TEXT,
                status TEXT,
                PRIMARY KEY (workflow_name, schedule_id)
            )
        """)

        # Schedules by status
        session.execute("""
            CREATE TABLE IF NOT EXISTS schedules_by_status (
                status TEXT,
                schedule_id TEXT,
                workflow_name TEXT,
                PRIMARY KEY (status, schedule_id)
            )
        """)

        # Due schedules with hourly buckets
        session.execute("""
            CREATE TABLE IF NOT EXISTS due_schedules (
                hour_bucket TEXT,
                next_run_time TIMESTAMP,
                schedule_id TEXT,
                status TEXT,
                PRIMARY KEY (hour_bucket, next_run_time, schedule_id)
            ) WITH CLUSTERING ORDER BY (next_run_time ASC, schedule_id ASC)
        """)

    async def _create_runs_query_tables(self, session: Session) -> None:
        """Create query pattern tables for runs."""
        # Runs by status with daily buckets
        session.execute("""
            CREATE TABLE IF NOT EXISTS runs_by_status (
                status TEXT,
                date_bucket TEXT,
                created_at TIMESTAMP,
                run_id TEXT,
                workflow_name TEXT,
                PRIMARY KEY ((status, date_bucket), created_at, run_id)
            ) WITH CLUSTERING ORDER BY (created_at DESC, run_id DESC)
        """)

        # Runs by workflow name with daily buckets
        session.execute("""
            CREATE TABLE IF NOT EXISTS runs_by_workflow (
                workflow_name TEXT,
                date_bucket TEXT,
                created_at TIMESTAMP,
                run_id TEXT,
                status TEXT,
                PRIMARY KEY ((workflow_name, date_bucket), created_at, run_id)
            ) WITH CLUSTERING ORDER BY (created_at DESC, run_id DESC)
        """)

        # Child workflows
        session.execute("""
            CREATE TABLE IF NOT EXISTS runs_by_parent (
                parent_run_id TEXT,
                created_at TIMESTAMP,
                run_id TEXT,
                status TEXT,
                PRIMARY KEY (parent_run_id, created_at, run_id)
            )
        """)

    # Helper methods

    def _get_date_bucket(self, dt: datetime) -> str:
        """Get date bucket string (YYYY-MM-DD) for time-based partitioning."""
        return dt.strftime("%Y-%m-%d")

    def _get_hour_bucket(self, dt: datetime) -> str:
        """Get hour bucket string (YYYY-MM-DD-HH) for schedule partitioning."""
        return dt.strftime("%Y-%m-%d-%H")

    def _get_date_buckets(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        max_buckets: int = 30,
    ) -> list[str]:
        """Generate list of date buckets to query, from newest to oldest."""
        end = end_time or datetime.now(UTC)
        start = start_time or (end - timedelta(days=max_buckets))

        buckets: list[str] = []
        current = end
        while current >= start and len(buckets) < max_buckets:
            buckets.append(self._get_date_bucket(current))
            current -= timedelta(days=1)

        return buckets

    def _generate_timeuuid(self) -> uuid.UUID:
        """Generate a time-based UUID (v1) for event ordering."""
        return uuid.uuid1()

    # Workflow Run Operations

    async def create_run(self, run: WorkflowRun) -> None:
        """Create a new workflow run record with denormalized writes."""
        session = self._ensure_connected()

        batch = BatchStatement(consistency_level=self.write_consistency)

        # Main workflow_runs table
        batch.add(
            SimpleStatement("""
                INSERT INTO workflow_runs (
                    run_id, workflow_name, status, created_at, updated_at,
                    started_at, completed_at, input_args, input_kwargs,
                    result, error, idempotency_key, max_duration, context,
                    recovery_attempts, max_recovery_attempts, recover_on_worker_loss,
                    parent_run_id, nesting_depth, continued_from_run_id, continued_to_run_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """),
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

        # Idempotency key lookup (if key provided)
        if run.idempotency_key:
            batch.add(
                SimpleStatement(
                    "INSERT INTO runs_by_idempotency_key (idempotency_key, run_id) VALUES (%s, %s)"
                ),
                (run.idempotency_key, run.run_id),
            )

        # Runs by status with date bucket
        date_bucket = self._get_date_bucket(run.created_at)
        batch.add(
            SimpleStatement("""
                INSERT INTO runs_by_status (status, date_bucket, created_at, run_id, workflow_name)
                VALUES (%s, %s, %s, %s, %s)
            """),
            (run.status.value, date_bucket, run.created_at, run.run_id, run.workflow_name),
        )

        # Runs by workflow name with date bucket
        batch.add(
            SimpleStatement("""
                INSERT INTO runs_by_workflow (workflow_name, date_bucket, created_at, run_id, status)
                VALUES (%s, %s, %s, %s, %s)
            """),
            (run.workflow_name, date_bucket, run.created_at, run.run_id, run.status.value),
        )

        # Parent-child relationship (if has parent)
        if run.parent_run_id:
            batch.add(
                SimpleStatement("""
                    INSERT INTO runs_by_parent (parent_run_id, created_at, run_id, status)
                    VALUES (%s, %s, %s, %s)
                """),
                (run.parent_run_id, run.created_at, run.run_id, run.status.value),
            )

        session.execute(batch)

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        """Retrieve a workflow run by ID."""
        session = self._ensure_connected()

        row = session.execute(
            SimpleStatement(
                "SELECT * FROM workflow_runs WHERE run_id = %s",
                consistency_level=self.read_consistency,
            ),
            (run_id,),
        ).one()

        if not row:
            return None

        return self._row_to_workflow_run(row)

    async def get_run_by_idempotency_key(self, key: str) -> WorkflowRun | None:
        """Retrieve a workflow run by idempotency key."""
        session = self._ensure_connected()

        # First lookup run_id from idempotency key table
        row = session.execute(
            SimpleStatement(
                "SELECT run_id FROM runs_by_idempotency_key WHERE idempotency_key = %s",
                consistency_level=self.read_consistency,
            ),
            (key,),
        ).one()

        if not row:
            return None

        return await self.get_run(row.run_id)

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update workflow run status."""
        session = self._ensure_connected()

        # Get current run to know date bucket and old status
        run = await self.get_run(run_id)
        if not run:
            return

        now = datetime.now(UTC)
        completed_at = now if status == RunStatus.COMPLETED else run.completed_at
        date_bucket = self._get_date_bucket(run.created_at)
        old_status = run.status.value
        new_status = status.value

        batch = BatchStatement(consistency_level=self.write_consistency)

        # Update main table
        batch.add(
            SimpleStatement("""
                UPDATE workflow_runs
                SET status = %s, updated_at = %s, result = %s, error = %s, completed_at = %s
                WHERE run_id = %s
            """),
            (new_status, now, result, error, completed_at, run_id),
        )

        # Update runs_by_status - delete old, insert new
        if old_status != new_status:
            batch.add(
                SimpleStatement("""
                    DELETE FROM runs_by_status
                    WHERE status = %s AND date_bucket = %s AND created_at = %s AND run_id = %s
                """),
                (old_status, date_bucket, run.created_at, run_id),
            )
            batch.add(
                SimpleStatement("""
                    INSERT INTO runs_by_status (status, date_bucket, created_at, run_id, workflow_name)
                    VALUES (%s, %s, %s, %s, %s)
                """),
                (new_status, date_bucket, run.created_at, run_id, run.workflow_name),
            )

        # Update runs_by_workflow status
        batch.add(
            SimpleStatement("""
                UPDATE runs_by_workflow
                SET status = %s
                WHERE workflow_name = %s AND date_bucket = %s AND created_at = %s AND run_id = %s
            """),
            (new_status, run.workflow_name, date_bucket, run.created_at, run_id),
        )

        # Update runs_by_parent status if has parent
        if run.parent_run_id:
            batch.add(
                SimpleStatement("""
                    UPDATE runs_by_parent
                    SET status = %s
                    WHERE parent_run_id = %s AND created_at = %s AND run_id = %s
                """),
                (new_status, run.parent_run_id, run.created_at, run_id),
            )

        session.execute(batch)

    async def update_run_recovery_attempts(
        self,
        run_id: str,
        recovery_attempts: int,
    ) -> None:
        """Update the recovery attempts counter for a workflow run."""
        session = self._ensure_connected()

        session.execute(
            SimpleStatement(
                """
                UPDATE workflow_runs
                SET recovery_attempts = %s, updated_at = %s
                WHERE run_id = %s
                """,
                consistency_level=self.write_consistency,
            ),
            (recovery_attempts, datetime.now(UTC), run_id),
        )

    async def update_run_context(
        self,
        run_id: str,
        context: dict,
    ) -> None:
        """Update the step context for a workflow run."""
        session = self._ensure_connected()

        session.execute(
            SimpleStatement(
                """
                UPDATE workflow_runs
                SET context = %s, updated_at = %s
                WHERE run_id = %s
                """,
                consistency_level=self.write_consistency,
            ),
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
        """List workflow runs with bucket walking pagination."""
        session = self._ensure_connected()

        # Get date buckets to query
        buckets = self._get_date_buckets(start_time, end_time)
        runs: list[WorkflowRun] = []

        # Decode cursor if provided
        cursor_created_at: datetime | None = None
        if cursor:
            cursor_run = await self.get_run(cursor)
            if cursor_run:
                cursor_created_at = cursor_run.created_at

        for bucket in buckets:
            if len(runs) >= limit:
                break

            if status:
                # Query runs_by_status table
                if cursor_created_at:
                    rows = session.execute(
                        SimpleStatement(
                            """
                            SELECT run_id FROM runs_by_status
                            WHERE status = %s AND date_bucket = %s AND created_at < %s
                            ORDER BY created_at DESC
                            LIMIT %s
                            """,
                            consistency_level=self.read_consistency,
                        ),
                        (status.value, bucket, cursor_created_at, limit - len(runs) + 1),
                    )
                else:
                    rows = session.execute(
                        SimpleStatement(
                            """
                            SELECT run_id FROM runs_by_status
                            WHERE status = %s AND date_bucket = %s
                            ORDER BY created_at DESC
                            LIMIT %s
                            """,
                            consistency_level=self.read_consistency,
                        ),
                        (status.value, bucket, limit - len(runs) + 1),
                    )
            else:
                # Without status filter, we need to scan multiple tables or use a different approach
                # For now, query all statuses in this bucket (less efficient but avoids ALLOW FILTERING)
                if cursor_created_at:
                    rows = session.execute(
                        SimpleStatement(
                            """
                            SELECT run_id FROM runs_by_workflow
                            WHERE workflow_name = %s AND date_bucket = %s AND created_at < %s
                            ORDER BY created_at DESC
                            LIMIT %s
                            """,
                            consistency_level=self.read_consistency,
                        ),
                        # This doesn't work without workflow_name, fall back to direct table scan
                        ("", bucket, cursor_created_at, limit - len(runs) + 1),
                    )
                    # Fall back: query workflow_runs directly with token range (less efficient)
                    rows = session.execute(
                        SimpleStatement(
                            """
                            SELECT * FROM workflow_runs
                            LIMIT %s
                            """,
                            consistency_level=self.read_consistency,
                        ),
                        (limit * 2,),  # Fetch more to filter
                    )
                else:
                    # Without filters, query workflow_runs directly
                    rows = session.execute(
                        SimpleStatement(
                            "SELECT * FROM workflow_runs LIMIT %s",
                            consistency_level=self.read_consistency,
                        ),
                        (limit * 2,),
                    )

            for row in rows:
                if len(runs) >= limit + 1:
                    break
                run = (
                    await self.get_run(row.run_id)
                    if hasattr(row, "run_id")
                    else self._row_to_workflow_run(row)
                )
                if run:
                    # Apply query filter if provided (case-insensitive substring)
                    if query:
                        if (
                            query.lower() not in run.workflow_name.lower()
                            and query.lower() not in run.input_kwargs.lower()
                        ):
                            continue
                    # Apply time filters
                    if start_time and run.created_at < start_time:
                        continue
                    if end_time and run.created_at >= end_time:
                        continue
                    runs.append(run)

            # Reset cursor after first bucket
            cursor_created_at = None

        # Sort by created_at descending
        runs.sort(key=lambda r: r.created_at, reverse=True)

        # Handle pagination
        has_more = len(runs) > limit
        if has_more:
            runs = runs[:limit]

        next_cursor = runs[-1].run_id if runs and has_more else None
        return runs, next_cursor

    # Event Log Operations

    async def record_event(self, event: Event) -> None:
        """Record an event with TIMEUUID for ordering."""
        session = self._ensure_connected()

        # Generate TIMEUUID for natural time ordering
        event_time = self._generate_timeuuid()

        session.execute(
            SimpleStatement(
                """
                INSERT INTO events (run_id, event_time, event_id, type, timestamp, data)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                consistency_level=self.write_consistency,
            ),
            (
                event.run_id,
                event_time,
                event.event_id,
                event.type.value,
                event.timestamp,
                json.dumps(event.data),
            ),
        )

    async def get_events(
        self,
        run_id: str,
        event_types: list[str] | None = None,
    ) -> list[Event]:
        """Retrieve all events for a workflow run, ordered by time."""
        session = self._ensure_connected()

        rows = session.execute(
            SimpleStatement(
                "SELECT * FROM events WHERE run_id = %s ORDER BY event_time ASC",
                consistency_level=self.read_consistency,
            ),
            (run_id,),
        )

        events = []
        for idx, row in enumerate(rows):
            # Filter by event types if specified (application-side filtering)
            if event_types and row.type not in event_types:
                continue
            events.append(self._row_to_event(row, sequence=idx))

        return events

    async def get_latest_event(
        self,
        run_id: str,
        event_type: str | None = None,
    ) -> Event | None:
        """Get the latest event for a run, optionally filtered by type."""
        session = self._ensure_connected()

        rows = session.execute(
            SimpleStatement(
                """
                SELECT * FROM events
                WHERE run_id = %s
                ORDER BY event_time DESC
                LIMIT %s
                """,
                consistency_level=self.read_consistency,
            ),
            (run_id, 10 if event_type else 1),
        )

        # Get total count for sequence number
        all_events = list(
            session.execute(
                SimpleStatement(
                    "SELECT event_time FROM events WHERE run_id = %s",
                    consistency_level=self.read_consistency,
                ),
                (run_id,),
            )
        )
        total_count = len(all_events)

        for row in rows:
            if event_type and row.type != event_type:
                continue
            return self._row_to_event(row, sequence=total_count - 1)

        return None

    # Step Operations

    async def create_step(self, step: StepExecution) -> None:
        """Create a step execution record."""
        session = self._ensure_connected()

        batch = BatchStatement(consistency_level=self.write_consistency)

        # Steps table
        batch.add(
            SimpleStatement("""
                INSERT INTO steps (
                    run_id, step_id, step_name, status, created_at, updated_at,
                    started_at, completed_at, input_args, input_kwargs,
                    result, error, attempt, max_retries, retry_after, retry_delay
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """),
            (
                step.run_id,
                step.step_id,
                step.step_name,
                step.status.value,
                step.created_at,
                step.updated_at,
                step.started_at,
                step.completed_at,
                step.input_args,
                step.input_kwargs,
                step.result,
                step.error,
                step.attempt,
                step.max_retries,
                step.retry_after,
                step.retry_delay,
            ),
        )

        # Steps lookup by ID
        batch.add(
            SimpleStatement("INSERT INTO steps_by_id (step_id, run_id) VALUES (%s, %s)"),
            (step.step_id, step.run_id),
        )

        session.execute(batch)

    async def get_step(self, step_id: str) -> StepExecution | None:
        """Retrieve a step execution by ID."""
        session = self._ensure_connected()

        # First lookup run_id
        lookup = session.execute(
            SimpleStatement(
                "SELECT run_id FROM steps_by_id WHERE step_id = %s",
                consistency_level=self.read_consistency,
            ),
            (step_id,),
        ).one()

        if not lookup:
            return None

        # Then get full step
        row = session.execute(
            SimpleStatement(
                "SELECT * FROM steps WHERE run_id = %s AND step_id = %s",
                consistency_level=self.read_consistency,
            ),
            (lookup.run_id, step_id),
        ).one()

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
        session = self._ensure_connected()

        # First lookup run_id
        lookup = session.execute(
            SimpleStatement(
                "SELECT run_id FROM steps_by_id WHERE step_id = %s",
                consistency_level=self.read_consistency,
            ),
            (step_id,),
        ).one()

        if not lookup:
            return

        now = datetime.now(UTC)
        completed_at = now if status == "completed" else None

        session.execute(
            SimpleStatement(
                """
                UPDATE steps
                SET status = %s, updated_at = %s, result = %s, error = %s, completed_at = %s
                WHERE run_id = %s AND step_id = %s
                """,
                consistency_level=self.write_consistency,
            ),
            (status, now, result, error, completed_at, lookup.run_id, step_id),
        )

    async def list_steps(self, run_id: str) -> list[StepExecution]:
        """List all steps for a workflow run."""
        session = self._ensure_connected()

        rows = session.execute(
            SimpleStatement(
                "SELECT * FROM steps WHERE run_id = %s",
                consistency_level=self.read_consistency,
            ),
            (run_id,),
        )

        steps = [self._row_to_step_execution(row) for row in rows]
        steps.sort(key=lambda s: s.created_at)
        return steps

    # Hook Operations

    async def create_hook(self, hook: Hook) -> None:
        """Create a hook record."""
        session = self._ensure_connected()

        batch = BatchStatement(consistency_level=self.write_consistency)

        # Hooks table
        batch.add(
            SimpleStatement("""
                INSERT INTO hooks (
                    run_id, hook_id, token, url, status, created_at,
                    received_at, expires_at, payload, name, payload_schema, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """),
            (
                hook.run_id,
                hook.hook_id,
                hook.token,
                hook.url,
                hook.status.value,
                hook.created_at,
                hook.received_at,
                hook.expires_at,
                hook.payload,
                hook.name,
                hook.payload_schema,
                json.dumps(hook.metadata),
            ),
        )

        # Hooks lookup by ID
        batch.add(
            SimpleStatement("INSERT INTO hooks_by_id (hook_id, run_id) VALUES (%s, %s)"),
            (hook.hook_id, hook.run_id),
        )

        # Hooks lookup by token
        batch.add(
            SimpleStatement(
                "INSERT INTO hooks_by_token (token, run_id, hook_id) VALUES (%s, %s, %s)"
            ),
            (hook.token, hook.run_id, hook.hook_id),
        )

        session.execute(batch)

    async def get_hook(self, hook_id: str) -> Hook | None:
        """Retrieve a hook by ID."""
        session = self._ensure_connected()

        # First lookup run_id
        lookup = session.execute(
            SimpleStatement(
                "SELECT run_id FROM hooks_by_id WHERE hook_id = %s",
                consistency_level=self.read_consistency,
            ),
            (hook_id,),
        ).one()

        if not lookup:
            return None

        # Then get full hook
        row = session.execute(
            SimpleStatement(
                "SELECT * FROM hooks WHERE run_id = %s AND hook_id = %s",
                consistency_level=self.read_consistency,
            ),
            (lookup.run_id, hook_id),
        ).one()

        if not row:
            return None

        return self._row_to_hook(row)

    async def get_hook_by_token(self, token: str) -> Hook | None:
        """Retrieve a hook by its token."""
        session = self._ensure_connected()

        # Lookup by token
        lookup = session.execute(
            SimpleStatement(
                "SELECT run_id, hook_id FROM hooks_by_token WHERE token = %s",
                consistency_level=self.read_consistency,
            ),
            (token,),
        ).one()

        if not lookup:
            return None

        # Get full hook
        row = session.execute(
            SimpleStatement(
                "SELECT * FROM hooks WHERE run_id = %s AND hook_id = %s",
                consistency_level=self.read_consistency,
            ),
            (lookup.run_id, lookup.hook_id),
        ).one()

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
        session = self._ensure_connected()

        # First lookup run_id
        lookup = session.execute(
            SimpleStatement(
                "SELECT run_id FROM hooks_by_id WHERE hook_id = %s",
                consistency_level=self.read_consistency,
            ),
            (hook_id,),
        ).one()

        if not lookup:
            return

        received_at = datetime.now(UTC) if status == HookStatus.RECEIVED else None

        session.execute(
            SimpleStatement(
                """
                UPDATE hooks
                SET status = %s, payload = %s, received_at = %s
                WHERE run_id = %s AND hook_id = %s
                """,
                consistency_level=self.write_consistency,
            ),
            (status.value, payload, received_at, lookup.run_id, hook_id),
        )

    async def list_hooks(
        self,
        run_id: str | None = None,
        status: HookStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Hook]:
        """List hooks with optional filtering."""
        session = self._ensure_connected()

        if run_id:
            rows = session.execute(
                SimpleStatement(
                    "SELECT * FROM hooks WHERE run_id = %s",
                    consistency_level=self.read_consistency,
                ),
                (run_id,),
            )
        else:
            # Without run_id, we'd need to scan all partitions
            # Return empty list - caller should provide run_id
            return []

        hooks = []
        for row in rows:
            hook = self._row_to_hook(row)
            # Apply status filter (application-side)
            if status and hook.status != status:
                continue
            hooks.append(hook)

        # Sort by created_at descending
        hooks.sort(key=lambda h: h.created_at, reverse=True)

        # Apply offset and limit
        return hooks[offset : offset + limit]

    # Cancellation Flag Operations

    async def set_cancellation_flag(self, run_id: str) -> None:
        """Set a cancellation flag for a workflow run."""
        session = self._ensure_connected()

        session.execute(
            SimpleStatement(
                "INSERT INTO cancellation_flags (run_id, created_at) VALUES (%s, %s)",
                consistency_level=self.write_consistency,
            ),
            (run_id, datetime.now(UTC)),
        )

    async def check_cancellation_flag(self, run_id: str) -> bool:
        """Check if a cancellation flag is set for a workflow run."""
        session = self._ensure_connected()

        row = session.execute(
            SimpleStatement(
                "SELECT run_id FROM cancellation_flags WHERE run_id = %s",
                consistency_level=self.read_consistency,
            ),
            (run_id,),
        ).one()

        return row is not None

    async def clear_cancellation_flag(self, run_id: str) -> None:
        """Clear the cancellation flag for a workflow run."""
        session = self._ensure_connected()

        session.execute(
            SimpleStatement(
                "DELETE FROM cancellation_flags WHERE run_id = %s",
                consistency_level=self.write_consistency,
            ),
            (run_id,),
        )

    # Continue-As-New Chain Operations

    async def update_run_continuation(
        self,
        run_id: str,
        continued_to_run_id: str,
    ) -> None:
        """Update the continuation link for a workflow run."""
        session = self._ensure_connected()

        session.execute(
            SimpleStatement(
                """
                UPDATE workflow_runs
                SET continued_to_run_id = %s, updated_at = %s
                WHERE run_id = %s
                """,
                consistency_level=self.write_consistency,
            ),
            (continued_to_run_id, datetime.now(UTC), run_id),
        )

    async def get_workflow_chain(
        self,
        run_id: str,
    ) -> list[WorkflowRun]:
        """Get all runs in a continue-as-new chain."""
        # Find the first run in the chain
        current_id: str | None = run_id
        while current_id:
            run = await self.get_run(current_id)
            if not run or not run.continued_from_run_id:
                break
            current_id = run.continued_from_run_id

        # Collect all runs from first to last
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
        session = self._ensure_connected()

        rows = session.execute(
            SimpleStatement(
                "SELECT run_id, status FROM runs_by_parent WHERE parent_run_id = %s",
                consistency_level=self.read_consistency,
            ),
            (parent_run_id,),
        )

        children = []
        for row in rows:
            # Filter by status if specified
            if status and row.status != status.value:
                continue
            run = await self.get_run(row.run_id)
            if run:
                children.append(run)

        children.sort(key=lambda r: r.created_at)
        return children

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
        session = self._ensure_connected()

        # Derive spec_type from ScheduleSpec
        spec_type = (
            "cron" if schedule.spec.cron else ("interval" if schedule.spec.interval else "calendar")
        )

        batch = BatchStatement(consistency_level=self.write_consistency)

        # Main schedules table
        batch.add(
            SimpleStatement("""
                INSERT INTO schedules (
                    schedule_id, workflow_name, spec, spec_type, timezone,
                    args, kwargs, status, overlap_policy, created_at, updated_at,
                    last_run_at, next_run_time, last_run_id, running_run_ids, buffered_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """),
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
                schedule.created_at,
                schedule.updated_at,
                schedule.last_run_at,
                schedule.next_run_time,
                schedule.last_run_id,
                json.dumps(schedule.running_run_ids),
                schedule.buffered_count,
            ),
        )

        # Schedules by workflow
        batch.add(
            SimpleStatement("""
                INSERT INTO schedules_by_workflow (workflow_name, schedule_id, status)
                VALUES (%s, %s, %s)
            """),
            (schedule.workflow_name, schedule.schedule_id, schedule.status.value),
        )

        # Schedules by status
        batch.add(
            SimpleStatement("""
                INSERT INTO schedules_by_status (status, schedule_id, workflow_name)
                VALUES (%s, %s, %s)
            """),
            (schedule.status.value, schedule.schedule_id, schedule.workflow_name),
        )

        # Due schedules (if active and has next_run_time)
        if schedule.status == ScheduleStatus.ACTIVE and schedule.next_run_time:
            hour_bucket = self._get_hour_bucket(schedule.next_run_time)
            batch.add(
                SimpleStatement("""
                    INSERT INTO due_schedules (hour_bucket, next_run_time, schedule_id, status)
                    VALUES (%s, %s, %s, %s)
                """),
                (hour_bucket, schedule.next_run_time, schedule.schedule_id, schedule.status.value),
            )

        session.execute(batch)

    async def get_schedule(self, schedule_id: str) -> Schedule | None:
        """Retrieve a schedule by ID."""
        session = self._ensure_connected()

        row = session.execute(
            SimpleStatement(
                "SELECT * FROM schedules WHERE schedule_id = %s",
                consistency_level=self.read_consistency,
            ),
            (schedule_id,),
        ).one()

        if not row:
            return None

        return self._row_to_schedule(row)

    async def update_schedule(self, schedule: Schedule) -> None:
        """Update an existing schedule."""
        session = self._ensure_connected()

        # Get old schedule to clean up denormalized tables
        old_schedule = await self.get_schedule(schedule.schedule_id)
        if not old_schedule:
            raise ValueError(f"Schedule {schedule.schedule_id} not found")

        # Derive spec_type from ScheduleSpec
        spec_type = (
            "cron" if schedule.spec.cron else ("interval" if schedule.spec.interval else "calendar")
        )

        batch = BatchStatement(consistency_level=self.write_consistency)

        # Update main table
        batch.add(
            SimpleStatement("""
                UPDATE schedules SET
                    workflow_name = %s, spec = %s, spec_type = %s, timezone = %s,
                    args = %s, kwargs = %s, status = %s, overlap_policy = %s,
                    updated_at = %s, last_run_at = %s, next_run_time = %s,
                    last_run_id = %s, running_run_ids = %s, buffered_count = %s
                WHERE schedule_id = %s
            """),
            (
                schedule.workflow_name,
                json.dumps(schedule.spec.to_dict()),
                spec_type,
                schedule.spec.timezone,
                schedule.args,
                schedule.kwargs,
                schedule.status.value,
                schedule.overlap_policy.value,
                schedule.updated_at or datetime.now(UTC),
                schedule.last_run_at,
                schedule.next_run_time,
                schedule.last_run_id,
                json.dumps(schedule.running_run_ids),
                schedule.buffered_count,
                schedule.schedule_id,
            ),
        )

        # Update schedules_by_workflow if status changed
        if old_schedule.status != schedule.status:
            batch.add(
                SimpleStatement("""
                    UPDATE schedules_by_workflow SET status = %s
                    WHERE workflow_name = %s AND schedule_id = %s
                """),
                (schedule.status.value, schedule.workflow_name, schedule.schedule_id),
            )

            # Delete from old status, insert into new status
            batch.add(
                SimpleStatement("""
                    DELETE FROM schedules_by_status
                    WHERE status = %s AND schedule_id = %s
                """),
                (old_schedule.status.value, schedule.schedule_id),
            )
            batch.add(
                SimpleStatement("""
                    INSERT INTO schedules_by_status (status, schedule_id, workflow_name)
                    VALUES (%s, %s, %s)
                """),
                (schedule.status.value, schedule.schedule_id, schedule.workflow_name),
            )

        # Update due_schedules if next_run_time changed
        if old_schedule.next_run_time != schedule.next_run_time:
            # Delete old entry
            if old_schedule.next_run_time:
                old_hour_bucket = self._get_hour_bucket(old_schedule.next_run_time)
                batch.add(
                    SimpleStatement("""
                        DELETE FROM due_schedules
                        WHERE hour_bucket = %s AND next_run_time = %s AND schedule_id = %s
                    """),
                    (old_hour_bucket, old_schedule.next_run_time, schedule.schedule_id),
                )
            # Insert new entry
            if schedule.status == ScheduleStatus.ACTIVE and schedule.next_run_time:
                new_hour_bucket = self._get_hour_bucket(schedule.next_run_time)
                batch.add(
                    SimpleStatement("""
                        INSERT INTO due_schedules (hour_bucket, next_run_time, schedule_id, status)
                        VALUES (%s, %s, %s, %s)
                    """),
                    (
                        new_hour_bucket,
                        schedule.next_run_time,
                        schedule.schedule_id,
                        schedule.status.value,
                    ),
                )

        session.execute(batch)

    async def delete_schedule(self, schedule_id: str) -> None:
        """Mark a schedule as deleted (soft delete)."""
        schedule = await self.get_schedule(schedule_id)
        if not schedule:
            return

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
        session = self._ensure_connected()

        if workflow_name:
            rows = session.execute(
                SimpleStatement(
                    "SELECT schedule_id, status FROM schedules_by_workflow WHERE workflow_name = %s",
                    consistency_level=self.read_consistency,
                ),
                (workflow_name,),
            )
        elif status:
            rows = session.execute(
                SimpleStatement(
                    "SELECT schedule_id FROM schedules_by_status WHERE status = %s",
                    consistency_level=self.read_consistency,
                ),
                (status.value,),
            )
        else:
            # Without filters, get from main table (less efficient)
            rows = session.execute(
                SimpleStatement(
                    "SELECT schedule_id FROM schedules LIMIT %s",
                    consistency_level=self.read_consistency,
                ),
                (limit * 2,),
            )

        schedules = []
        for row in rows:
            schedule = await self.get_schedule(row.schedule_id)
            if schedule:
                # Apply status filter if querying by workflow_name
                if workflow_name and status and schedule.status != status:
                    continue
                schedules.append(schedule)

        # Sort by created_at descending
        schedules.sort(key=lambda s: s.created_at, reverse=True)

        # Apply offset and limit
        return schedules[offset : offset + limit]

    async def get_due_schedules(self, now: datetime) -> list[Schedule]:
        """Get all schedules that are due to run."""
        session = self._ensure_connected()

        due_schedules = []

        # Query current hour and previous 24 hours (in case of delays)
        for hours_ago in range(25):
            bucket_time = now - timedelta(hours=hours_ago)
            hour_bucket = self._get_hour_bucket(bucket_time)

            rows = session.execute(
                SimpleStatement(
                    """
                    SELECT schedule_id FROM due_schedules
                    WHERE hour_bucket = %s AND next_run_time <= %s
                    """,
                    consistency_level=self.read_consistency,
                ),
                (hour_bucket, now),
            )

            for row in rows:
                schedule = await self.get_schedule(row.schedule_id)
                if schedule and schedule.status == ScheduleStatus.ACTIVE:
                    due_schedules.append(schedule)

        # Remove duplicates and sort by next_run_time
        seen = set()
        unique_schedules = []
        for s in due_schedules:
            if s.schedule_id not in seen:
                seen.add(s.schedule_id)
                unique_schedules.append(s)

        unique_schedules.sort(key=lambda s: s.next_run_time or datetime.min.replace(tzinfo=UTC))
        return unique_schedules

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

    # Helper methods for converting Cassandra rows to domain objects

    def _row_to_workflow_run(self, row: Any) -> WorkflowRun:
        """Convert Cassandra row to WorkflowRun object."""
        return WorkflowRun(
            run_id=row.run_id,
            workflow_name=row.workflow_name,
            status=RunStatus(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            input_args=row.input_args or "[]",
            input_kwargs=row.input_kwargs or "{}",
            result=row.result,
            error=row.error,
            idempotency_key=row.idempotency_key,
            max_duration=row.max_duration,
            context=json.loads(row.context) if row.context else {},
            recovery_attempts=row.recovery_attempts or 0,
            max_recovery_attempts=row.max_recovery_attempts or 3,
            recover_on_worker_loss=row.recover_on_worker_loss
            if row.recover_on_worker_loss is not None
            else True,
            parent_run_id=row.parent_run_id,
            nesting_depth=row.nesting_depth or 0,
            continued_from_run_id=row.continued_from_run_id,
            continued_to_run_id=row.continued_to_run_id,
        )

    def _row_to_event(self, row: Any, sequence: int = 0) -> Event:
        """Convert Cassandra row to Event object."""
        return Event(
            event_id=row.event_id,
            run_id=row.run_id,
            sequence=sequence,
            type=EventType(row.type),
            timestamp=row.timestamp,
            data=json.loads(row.data) if row.data else {},
        )

    def _row_to_step_execution(self, row: Any) -> StepExecution:
        """Convert Cassandra row to StepExecution object."""
        return StepExecution(
            step_id=row.step_id,
            run_id=row.run_id,
            step_name=row.step_name,
            status=StepStatus(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            input_args=row.input_args or "[]",
            input_kwargs=row.input_kwargs or "{}",
            result=row.result,
            error=row.error,
            attempt=row.attempt or 1,
            max_retries=row.max_retries or 3,
            retry_after=row.retry_after,
            retry_delay=row.retry_delay,
        )

    def _row_to_hook(self, row: Any) -> Hook:
        """Convert Cassandra row to Hook object."""
        return Hook(
            hook_id=row.hook_id,
            run_id=row.run_id,
            token=row.token,
            url=row.url or "",
            status=HookStatus(row.status),
            created_at=row.created_at,
            received_at=row.received_at,
            expires_at=row.expires_at,
            payload=row.payload,
            name=row.name,
            payload_schema=row.payload_schema,
            metadata=json.loads(row.metadata) if row.metadata else {},
        )

    def _row_to_schedule(self, row: Any) -> Schedule:
        """Convert Cassandra row to Schedule object."""
        spec_data = json.loads(row.spec) if row.spec else {}
        spec = ScheduleSpec.from_dict(spec_data)

        return Schedule(
            schedule_id=row.schedule_id,
            workflow_name=row.workflow_name,
            spec=spec,
            status=ScheduleStatus(row.status),
            args=row.args or "[]",
            kwargs=row.kwargs or "{}",
            overlap_policy=OverlapPolicy(row.overlap_policy),
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_run_at=row.last_run_at,
            next_run_time=row.next_run_time,
            last_run_id=row.last_run_id,
            running_run_ids=json.loads(row.running_run_ids) if row.running_run_ids else [],
            buffered_count=row.buffered_count or 0,
        )
