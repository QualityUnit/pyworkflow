"""
Citus distributed PostgreSQL storage backend.

Citus is a PostgreSQL extension that shards tables across multiple nodes for
horizontal scalability. This backend extends PostgresStorageBackend, reusing all
query logic while overriding schema initialization to create Citus-compatible
distributed tables.

Distribution strategy:
- All workflow tables are co-located on `run_id` so that all data for a given
  workflow run lands on the same Citus shard.
- Schedules are distributed on `schedule_id` (independent of workflow runs).
- `schema_versions` becomes a reference table (replicated to all workers).

Citus constraints vs plain PostgreSQL:
- Primary keys and unique constraints MUST include the distribution column.
- Cross-shard foreign key constraints are unsupported.
- Global unique constraints on non-distribution columns cannot be enforced.

See: https://docs.citusdata.com/en/stable/develop/api.html
"""

import asyncpg

from pyworkflow.storage.migrations import Migration
from pyworkflow.storage.postgres import PostgresMigrationRunner, PostgresStorageBackend


class CitusMigrationRunner(PostgresMigrationRunner):
    """
    Citus-specific migration runner.

    Extends PostgresMigrationRunner to handle Citus schema constraints.
    V2 migration: same step_id backfill as PostgreSQL, but skips creating
    unique constraints that would conflict with Citus distribution requirements.
    """

    async def apply_migration(self, migration: Migration) -> None:
        """Apply a migration with Citus-specific handling."""
        from datetime import UTC, datetime

        async with self._pool.acquire() as conn, conn.transaction():
            if migration.version == 2:
                # V2: Add step_id column to events table
                # Check if events table exists (fresh databases won't have it yet)
                table_exists = await conn.fetchrow("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'events'
                    ) as exists
                """)

                if table_exists and table_exists["exists"]:
                    # Use IF NOT EXISTS for idempotency
                    await conn.execute("""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'events' AND column_name = 'step_id'
                            ) THEN
                                ALTER TABLE events ADD COLUMN step_id TEXT;
                            END IF;
                        END $$
                    """)

                    # Create index for optimized has_event() queries
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_events_run_id_step_id_type
                        ON events(run_id, step_id, type)
                    """)

                    # Backfill step_id from JSON data
                    await conn.execute("""
                        UPDATE events
                        SET step_id = (data::jsonb)->>'step_id'
                        WHERE step_id IS NULL
                          AND (data::jsonb)->>'step_id' IS NOT NULL
                    """)
                # NOTE: No UNIQUE constraints added here — Citus requires distribution
                # column in every unique constraint, which V2 doesn't add.
            elif migration.version == 3:
                # V3: Restructure signals table — PK changes to (stream_id, stream_run_id, sequence).
                # Must undistribute before dropping on Citus.
                await conn.execute("DROP TABLE IF EXISTS signal_acknowledgments")
                await conn.execute("DROP TABLE IF EXISTS signals")
                await conn.execute("""
                    CREATE TABLE signals (
                        stream_run_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        signal_id TEXT NOT NULL,
                        stream_id TEXT NOT NULL,
                        signal_type TEXT NOT NULL,
                        payload JSONB NOT NULL DEFAULT '{}',
                        published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        source_run_id TEXT,
                        metadata JSONB DEFAULT '{}',
                        PRIMARY KEY (stream_id, stream_run_id, sequence)
                    )
                """)
                await conn.execute("CREATE INDEX idx_signals_signal_id ON signals(signal_id)")
                await conn.execute("""
                    CREATE TABLE signal_acknowledgments (
                        signal_id TEXT NOT NULL,
                        step_run_id TEXT NOT NULL,
                        acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (signal_id, step_run_id)
                    )
                """)
                # Re-distribute the new tables
                await conn.execute("SELECT create_distributed_table('signals', 'stream_run_id')")
                await conn.execute("SELECT create_reference_table('signal_acknowledgments')")
            elif migration.version == 4:
                # V4: Drop FK constraints referencing streams table.
                # Citus never created these FKs (cross-shard FKs unsupported),
                # so this is a no-op but we still record the version.
                pass
            elif migration.version == 5:
                # V5: Add stream_run_id to stream_subscriptions + scheduled_signals table
                await conn.execute("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'stream_subscriptions'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'stream_subscriptions'
                              AND column_name = 'stream_run_id'
                        ) THEN
                            ALTER TABLE stream_subscriptions ADD COLUMN stream_run_id TEXT NULL;
                        END IF;
                    END $$
                """)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_subscriptions_stream_run "
                    "ON stream_subscriptions(stream_id, stream_run_id)"
                )
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS scheduled_signals (
                        id TEXT PRIMARY KEY,
                        stream_id TEXT NOT NULL,
                        signal_type TEXT NOT NULL,
                        payload JSONB NOT NULL DEFAULT '{}',
                        due_at TIMESTAMPTZ NOT NULL,
                        stream_run_id TEXT,
                        metadata JSONB DEFAULT '{}',
                        delivered BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_scheduled_signals_due "
                    "ON scheduled_signals(delivered, due_at)"
                )
                # Distribute as reference table if not already distributed
                already = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_dist_partition dp
                        JOIN pg_class c ON dp.logicalrelid = c.oid
                        WHERE c.relname = 'scheduled_signals'
                    )
                """)
                if not already:
                    await conn.execute("SELECT create_reference_table('scheduled_signals')")
            elif migration.version == 6:
                # V6: Add parent_run_id + parent_hook_token to stream_subscriptions
                await conn.execute("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'stream_subscriptions'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'stream_subscriptions'
                              AND column_name = 'parent_run_id'
                        ) THEN
                            ALTER TABLE stream_subscriptions
                                ADD COLUMN parent_run_id TEXT NULL,
                                ADD COLUMN parent_hook_token TEXT NULL;
                        END IF;
                    END $$
                """)
            elif migration.version == 7:
                await conn.execute("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'stream_subscriptions'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'stream_subscriptions'
                              AND column_name = 'result'
                        ) THEN
                            ALTER TABLE stream_subscriptions
                                ADD COLUMN result JSONB NULL;
                        END IF;
                    END $$
                """)
            elif migration.up_func:
                await migration.up_func(conn)
            elif migration.up_sql and migration.up_sql != "SELECT 1":
                await conn.execute(migration.up_sql)

            # Record the migration
            await conn.execute(
                """
                INSERT INTO schema_versions (version, applied_at, description)
                VALUES ($1, $2, $3)
                """,
                migration.version,
                datetime.now(UTC),
                migration.description,
            )


class CitusStorageBackend(PostgresStorageBackend):
    """
    Citus distributed PostgreSQL storage backend.

    Extends PostgresStorageBackend with Citus-specific schema initialization.
    All query logic is inherited unchanged — only DDL differs to satisfy Citus's
    distribution column requirements.

    Tables are sharded as follows:
    - workflow_runs, events, steps, hooks, cancellation_flags: distributed on run_id
    - schedules: distributed on schedule_id
    - schema_versions: reference table (replicated to all workers)

    Requirements:
    - PostgreSQL with the Citus extension installed and loaded
    - The calling database user must have permission to call Citus functions

    Usage:
        backend = CitusStorageBackend(
            host="citus-coordinator",
            database="pyworkflow",
        )
        await backend.connect()
    """

    async def _initialize_schema(self) -> None:
        """
        Create Citus-compatible schema and distribute tables.

        Steps:
        1. Verify Citus extension is available.
        2. Create tables with Citus-compatible PKs/constraints (no cross-shard FKs,
           no cross-shard UNIQUE constraints, composite PKs include distribution col).
        3. Create indexes.
        4. Distribute tables (idempotent — already-distributed tables are skipped).
        5. Run migrations via CitusMigrationRunner.
        """
        pool = await self._get_pool()

        # Step 1: Verify Citus extension is present
        async with pool.acquire() as conn:
            try:
                await conn.fetchval("SELECT citus_version()")
            except asyncpg.UndefinedFunctionError:
                raise RuntimeError(
                    "Citus extension is not available on this PostgreSQL server. "
                    "Install Citus and run `CREATE EXTENSION citus;` before using "
                    "CitusStorageBackend. See: https://docs.citusdata.com/en/stable/installation/"
                )

        # Step 2 & 3: Create tables and indexes with Citus-compatible DDL
        async with pool.acquire() as conn:
            # schema_versions — created first so CitusMigrationRunner can use it
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_versions (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL,
                    description TEXT
                )
            """)

            # workflow_runs — distributed on run_id
            # Differences vs postgres:
            #   - DROP FK on parent_run_id (self-referential FK can't be enforced cross-shard)
            #   - UNIQUE INDEX on idempotency_key → plain INDEX (global uniqueness unenforceable)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    input_args TEXT NOT NULL DEFAULT '[]',
                    input_kwargs TEXT NOT NULL DEFAULT '{}',
                    result TEXT,
                    error TEXT,
                    idempotency_key TEXT,
                    max_duration TEXT,
                    metadata TEXT DEFAULT '{}',
                    recovery_attempts INTEGER DEFAULT 0,
                    max_recovery_attempts INTEGER DEFAULT 3,
                    recover_on_worker_loss BOOLEAN DEFAULT TRUE,
                    parent_run_id TEXT,
                    nesting_depth INTEGER DEFAULT 0,
                    continued_from_run_id TEXT,
                    continued_to_run_id TEXT
                )
            """)

            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_status ON workflow_runs(status)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_workflow_name ON workflow_runs(workflow_name)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_created_at ON workflow_runs(created_at DESC)"
            )
            # Non-unique index: Citus cannot enforce global uniqueness on non-distribution columns
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_idempotency_key ON workflow_runs(idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_parent_run_id ON workflow_runs(parent_run_id)"
            )

            # events — distributed on run_id, co-located with workflow_runs
            # Differences vs postgres:
            #   - PK: event_id → (run_id, event_id) to include distribution column
            #   - FK on run_id retained (co-located FK is supported by Citus)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}',
                    step_id TEXT,
                    PRIMARY KEY (run_id, event_id)
                )
            """)

            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_run_id_sequence ON events(run_id, sequence)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_run_id_type ON events(run_id, type)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_run_id_step_id_type ON events(run_id, step_id, type)"
            )

            # steps — distributed on run_id, co-located with workflow_runs
            # Differences vs postgres:
            #   - PK: step_id → (run_id, step_id) to include distribution column
            #   - FK on run_id retained (co-located FK)
            #   - Extra index on step_id alone for get_step(step_id) scatter-gather queries
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS steps (
                    step_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    input_args TEXT NOT NULL DEFAULT '[]',
                    input_kwargs TEXT NOT NULL DEFAULT '{}',
                    result TEXT,
                    error TEXT,
                    retry_count INTEGER DEFAULT 0,
                    PRIMARY KEY (run_id, step_id)
                )
            """)

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps(run_id)")
            # Shard-local index to speed up get_step(step_id) scatter-gather queries
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_steps_step_id ON steps(step_id)")

            # hooks — distributed on run_id, co-located with workflow_runs
            # Differences vs postgres:
            #   - UNIQUE on token → plain INDEX (token = run_id:hook_id, collisions impossible)
            #   - FK on run_id retained (co-located FK)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS hooks (
                    run_id TEXT NOT NULL,
                    hook_id TEXT NOT NULL,
                    token TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    received_at TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ,
                    status TEXT NOT NULL,
                    payload TEXT,
                    metadata TEXT DEFAULT '{}',
                    PRIMARY KEY (run_id, hook_id)
                )
            """)

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_hooks_token ON hooks(token)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_hooks_run_id ON hooks(run_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_hooks_status ON hooks(status)")

            # schedules — distributed on schedule_id (independent of runs)
            await conn.execute("""
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
                    next_run_time TIMESTAMPTZ,
                    last_run_time TIMESTAMPTZ,
                    running_run_ids TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    paused_at TIMESTAMPTZ,
                    deleted_at TIMESTAMPTZ
                )
            """)

            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedules_status ON schedules(status)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedules_next_run_time ON schedules(next_run_time)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedules_workflow_name ON schedules(workflow_name)"
            )

            # cancellation_flags — distributed on run_id, co-located with workflow_runs
            # Differences vs postgres:
            #   - FK on run_id dropped (cross-shard FK unsupported; co-location ensures correctness)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS cancellation_flags (
                    run_id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)

            # checkpoints — reference table (keyed by step_run_id, not run_id)
            # Differences vs postgres:
            #   - No FK constraints (cross-shard FKs unsupported)
            #   - Distributed as reference table since step_run_id != run_id distribution key
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    step_run_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # streams — reference table (independent, keyed by stream_id)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS streams (
                    stream_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    metadata JSONB DEFAULT '{}'
                )
            """)

            # signals — distributed on stream_run_id
            # Differences vs postgres:
            #   - PK: (stream_id, stream_run_id, sequence) — distribution column is stream_run_id
            #   - No FK constraints (cross-shard FKs unsupported)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    stream_run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    signal_id TEXT NOT NULL,
                    stream_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}',
                    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    source_run_id TEXT,
                    metadata JSONB DEFAULT '{}',
                    PRIMARY KEY (stream_id, stream_run_id, sequence)
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_signal_id ON signals(signal_id)"
            )

            # stream_subscriptions — distributed on stream_id, co-located with signals
            # Differences vs postgres:
            #   - PK: (stream_id, step_run_id) to include distribution column
            #   - No FK constraints (cross-shard FKs unsupported)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stream_subscriptions (
                    stream_id TEXT NOT NULL,
                    step_run_id TEXT NOT NULL,
                    signal_types JSONB NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'waiting',
                    stream_run_id TEXT NULL,
                    parent_run_id TEXT NULL,
                    parent_hook_token TEXT NULL,
                    result JSONB NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (stream_id, step_run_id)
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON stream_subscriptions(stream_id, status)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_stream_run "
                "ON stream_subscriptions(stream_id, stream_run_id)"
            )

            # scheduled_signals — reference table (polled globally by runtime)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_signals (
                    id TEXT PRIMARY KEY,
                    stream_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}',
                    due_at TIMESTAMPTZ NOT NULL,
                    stream_run_id TEXT,
                    metadata JSONB DEFAULT '{}',
                    delivered BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_signals_due "
                "ON scheduled_signals(delivered, due_at)"
            )

            # signal_acknowledgments — reference table (needs cross-shard joins)
            # Differences vs postgres:
            #   - No FK constraints (cross-shard FKs unsupported)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS signal_acknowledgments (
                    signal_id TEXT NOT NULL,
                    step_run_id TEXT NOT NULL,
                    acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (signal_id, step_run_id)
                )
            """)

        # Step 4: Distribute tables (idempotent — already-distributed tables are skipped)
        await self._distribute_tables(pool)

        # Step 5: Run migrations via Citus-aware runner
        runner = CitusMigrationRunner(pool)
        await runner.run_migrations()

    async def _distribute_tables(self, pool: asyncpg.Pool) -> None:
        """
        Call Citus distribution functions for each table.

        Uses pg_dist_partition to detect already-distributed tables so this
        method is idempotent and safe to call on every connect().
        """
        async with pool.acquire() as conn:
            # Fetch already-distributed table names using relname to avoid
            # schema-prefix ambiguity (logicalrelid::text is search_path-dependent)
            rows = await conn.fetch("""
                SELECT c.relname AS tbl
                FROM pg_dist_partition dp
                JOIN pg_class c ON dp.logicalrelid = c.oid
            """)
            distributed = {row["tbl"] for row in rows}

            # workflow_runs: anchor table, distribute first
            if "workflow_runs" not in distributed:
                await conn.execute("SELECT create_distributed_table('workflow_runs', 'run_id')")

            # Co-located tables: must reference the same distribution column
            colocated_run_id = ["events", "steps", "hooks", "cancellation_flags"]
            for table in colocated_run_id:
                if table not in distributed:
                    await conn.execute(
                        f"SELECT create_distributed_table('{table}', 'run_id', "
                        f"colocate_with => 'workflow_runs')"
                    )

            # schedules: independent distribution
            if "schedules" not in distributed:
                await conn.execute("SELECT create_distributed_table('schedules', 'schedule_id')")

            # schema_versions: reference table (replicated to all workers)
            if "schema_versions" not in distributed:
                await conn.execute("SELECT create_reference_table('schema_versions')")

            # checkpoints: reference table (keyed by step_run_id, can't co-locate with run_id)
            if "checkpoints" not in distributed:
                await conn.execute("SELECT create_reference_table('checkpoints')")

            # streams: reference table (independent, small)
            if "streams" not in distributed:
                await conn.execute("SELECT create_reference_table('streams')")

            # signals: distributed on stream_run_id
            if "signals" not in distributed:
                await conn.execute("SELECT create_distributed_table('signals', 'stream_run_id')")

            # stream_subscriptions: distributed on stream_id (independent from signals)
            if "stream_subscriptions" not in distributed:
                await conn.execute(
                    "SELECT create_distributed_table('stream_subscriptions', 'stream_id')"
                )

            # signal_acknowledgments: reference table (needs cross-shard joins)
            if "signal_acknowledgments" not in distributed:
                await conn.execute("SELECT create_reference_table('signal_acknowledgments')")

            # scheduled_signals: reference table (polled globally by runtime)
            if "scheduled_signals" not in distributed:
                await conn.execute("SELECT create_reference_table('scheduled_signals')")
