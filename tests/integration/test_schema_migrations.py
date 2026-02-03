"""
Integration tests for schema migration framework.

Tests that migrations work correctly with real databases and that
the step_id optimization is properly applied.
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pyworkflow.engine.events import Event, EventType
from pyworkflow.storage.schemas import RunStatus, WorkflowRun
from pyworkflow.storage.sqlite import SQLiteStorageBackend


class TestSQLiteMigrations:
    """Test migrations work correctly with SQLite."""

    @pytest.fixture
    async def backend(self, tmp_path):
        """Create a fresh SQLite backend for each test."""
        db_path = tmp_path / "test.db"
        backend = SQLiteStorageBackend(db_path=str(db_path))
        await backend.connect()
        yield backend
        await backend.disconnect()

    @pytest.mark.asyncio
    async def test_fresh_database_has_schema_versions(self, backend):
        """Test that fresh database has schema_versions table."""
        async with backend._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_versions'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None, "schema_versions table should exist"

    @pytest.mark.asyncio
    async def test_fresh_database_has_migrations_applied(self, backend):
        """Test that fresh database has V1 and V2 migrations applied."""
        async with backend._db.execute(
            "SELECT version, description FROM schema_versions ORDER BY version"
        ) as cursor:
            rows = await cursor.fetchall()

        versions = [row[0] for row in rows]
        # Fresh database should have both V1 and V2 applied
        assert 1 in versions
        assert 2 in versions

    @pytest.mark.asyncio
    async def test_events_table_has_step_id_column(self, backend):
        """Test that events table has step_id column after migration."""
        async with backend._db.execute("PRAGMA table_info(events)") as cursor:
            columns = await cursor.fetchall()

        column_names = [col[1] for col in columns]
        assert "step_id" in column_names, "step_id column should exist in events table"

    @pytest.mark.asyncio
    async def test_events_table_has_step_id_index(self, backend):
        """Test that events table has the composite index for step_id."""
        async with backend._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_events_run_id_step_id_type'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None, "idx_events_run_id_step_id_type index should exist"

    @pytest.mark.asyncio
    async def test_record_event_populates_step_id(self, backend):
        """Test that record_event populates the step_id column."""
        # Create a workflow run first
        run = WorkflowRun(
            run_id="test_run_001",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await backend.create_run(run)

        # Record an event with step_id in data
        event = Event(
            event_id="evt_001",
            run_id="test_run_001",
            type=EventType.STEP_COMPLETED,
            timestamp=datetime.now(UTC),
            data={"step_id": "step_123", "result": "success"},
        )
        await backend.record_event(event)

        # Verify step_id column is populated
        async with backend._db.execute(
            "SELECT step_id FROM events WHERE event_id = ?", ("evt_001",)
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] == "step_123", "step_id column should be populated from event data"

    @pytest.mark.asyncio
    async def test_record_event_without_step_id(self, backend):
        """Test that record_event handles events without step_id."""
        run = WorkflowRun(
            run_id="test_run_002",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await backend.create_run(run)

        # Record an event without step_id
        event = Event(
            event_id="evt_002",
            run_id="test_run_002",
            type=EventType.WORKFLOW_STARTED,
            timestamp=datetime.now(UTC),
            data={"workflow_name": "test"},
        )
        await backend.record_event(event)

        # Verify step_id column is NULL
        async with backend._db.execute(
            "SELECT step_id FROM events WHERE event_id = ?", ("evt_002",)
        ) as cursor:
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] is None, "step_id column should be NULL for events without step_id"

    @pytest.mark.asyncio
    async def test_has_event_uses_optimized_query(self, backend):
        """Test that has_event uses the optimized indexed query for step_id filter."""
        run = WorkflowRun(
            run_id="test_run_003",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await backend.create_run(run)

        # Record multiple events
        for i in range(5):
            event = Event(
                event_id=f"evt_003_{i}",
                run_id="test_run_003",
                type=EventType.STEP_COMPLETED,
                timestamp=datetime.now(UTC),
                data={"step_id": f"step_{i}", "result": "success"},
            )
            await backend.record_event(event)

        # Test has_event with step_id filter (uses optimized query)
        result = await backend.has_event(
            "test_run_003",
            EventType.STEP_COMPLETED.value,
            step_id="step_2",
        )
        assert result is True

        # Test has_event with non-existent step_id
        result = await backend.has_event(
            "test_run_003",
            EventType.STEP_COMPLETED.value,
            step_id="step_999",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_has_event_fallback_for_other_filters(self, backend):
        """Test that has_event falls back to Python filtering for non-step_id filters."""
        run = WorkflowRun(
            run_id="test_run_004",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await backend.create_run(run)

        event = Event(
            event_id="evt_004",
            run_id="test_run_004",
            type=EventType.STEP_COMPLETED,
            timestamp=datetime.now(UTC),
            data={"step_id": "step_1", "result": "success", "custom_field": "custom_value"},
        )
        await backend.record_event(event)

        # Test has_event with non-step_id filter (uses fallback)
        result = await backend.has_event(
            "test_run_004",
            EventType.STEP_COMPLETED.value,
            custom_field="custom_value",
        )
        assert result is True

        result = await backend.has_event(
            "test_run_004",
            EventType.STEP_COMPLETED.value,
            custom_field="wrong_value",
        )
        assert result is False


class TestMigrationIdempotency:
    """Test that migrations are idempotent."""

    @pytest.mark.asyncio
    async def test_connect_twice_doesnt_duplicate_migrations(self, tmp_path):
        """Test that connecting twice doesn't duplicate migrations."""
        db_path = tmp_path / "idempotent_test.db"
        backend = SQLiteStorageBackend(db_path=str(db_path))

        # Connect twice
        await backend.connect()
        await backend.disconnect()
        await backend.connect()

        # Check migrations are only recorded once
        async with backend._db.execute(
            "SELECT version FROM schema_versions ORDER BY version"
        ) as cursor:
            rows = await cursor.fetchall()

        versions = [row[0] for row in rows]
        assert versions == [1, 2], "Each migration should only be recorded once"

        await backend.disconnect()

    @pytest.mark.asyncio
    async def test_reconnect_with_existing_data(self, tmp_path):
        """Test that reconnecting preserves existing data."""
        db_path = tmp_path / "preserve_data_test.db"

        # First connection - create some data
        backend1 = SQLiteStorageBackend(db_path=str(db_path))
        await backend1.connect()

        run = WorkflowRun(
            run_id="persistent_run",
            workflow_name="test_workflow",
            status=RunStatus.RUNNING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await backend1.create_run(run)

        event = Event(
            event_id="persistent_event",
            run_id="persistent_run",
            type=EventType.STEP_COMPLETED,
            timestamp=datetime.now(UTC),
            data={"step_id": "persistent_step", "result": "success"},
        )
        await backend1.record_event(event)
        await backend1.disconnect()

        # Second connection - verify data persists
        backend2 = SQLiteStorageBackend(db_path=str(db_path))
        await backend2.connect()

        # Verify run exists
        loaded_run = await backend2.get_run("persistent_run")
        assert loaded_run is not None
        assert loaded_run.workflow_name == "test_workflow"

        # Verify has_event with optimized query still works
        result = await backend2.has_event(
            "persistent_run",
            EventType.STEP_COMPLETED.value,
            step_id="persistent_step",
        )
        assert result is True

        await backend2.disconnect()
