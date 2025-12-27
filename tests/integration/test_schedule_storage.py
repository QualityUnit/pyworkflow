"""
Integration tests for schedule storage operations.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest

from pyworkflow.storage.file import FileStorageBackend
from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import (
    Schedule,
    ScheduleSpec,
    ScheduleStatus,
)
from pyworkflow.storage.sqlite import SQLiteStorageBackend

# Check if PostgreSQL is available
try:
    from pyworkflow.storage.postgres import PostgresStorageBackend

    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# Get PostgreSQL connection info from environment
POSTGRES_DSN = os.environ.get(
    "TEST_POSTGRES_DSN", "postgresql://pyworkflow:pyworkflow@localhost:5432/pyworkflow_test"
)


@pytest.fixture
def memory_storage():
    """Create an in-memory storage backend."""
    return InMemoryStorageBackend()


@pytest.fixture
def file_storage(tmp_path):
    """Create a file storage backend."""
    return FileStorageBackend(base_path=str(tmp_path))


@pytest.fixture
async def sqlite_storage(tmp_path):
    """Create a SQLite storage backend."""
    backend = SQLiteStorageBackend(db_path=str(tmp_path / "test.db"))
    await backend.connect()
    yield backend
    await backend.disconnect()


@pytest.fixture
async def postgres_storage():
    """Create a PostgreSQL storage backend."""
    if not POSTGRES_AVAILABLE:
        yield None
        return

    backend = PostgresStorageBackend(dsn=POSTGRES_DSN)
    connected = False
    try:
        await backend.connect()
        connected = True
        yield backend
    except Exception:
        yield None
    finally:
        if connected and backend._pool is not None:
            await backend.disconnect()


def get_storage_params():
    """Get storage backend parameters based on availability."""
    params = ["memory", "file", "sqlite"]
    if POSTGRES_AVAILABLE and os.environ.get("TEST_POSTGRES_ENABLED", "").lower() == "true":
        params.append("postgres")
    return params


@pytest.fixture(params=get_storage_params())
async def storage(request, memory_storage, file_storage, sqlite_storage, postgres_storage):
    """Parametrized fixture for all available storage backends."""
    if request.param == "memory":
        return memory_storage
    elif request.param == "file":
        return file_storage
    elif request.param == "sqlite":
        return sqlite_storage
    elif request.param == "postgres":
        if postgres_storage is None:
            pytest.skip("PostgreSQL not accessible")
        return postgres_storage
    raise ValueError(f"Unknown storage type: {request.param}")


class TestScheduleStorageCRUD:
    """Test basic CRUD operations for schedules."""

    @pytest.mark.asyncio
    async def test_create_schedule(self, storage):
        """Test creating a schedule."""
        spec = ScheduleSpec(cron="0 9 * * *")
        schedule = Schedule(
            schedule_id="test_schedule_1",
            workflow_name="test_workflow",
            spec=spec,
            created_at=datetime.now(UTC),
        )

        await storage.create_schedule(schedule)

        # Retrieve and verify
        retrieved = await storage.get_schedule("test_schedule_1")
        assert retrieved is not None
        assert retrieved.schedule_id == "test_schedule_1"
        assert retrieved.workflow_name == "test_workflow"
        assert retrieved.spec.cron == "0 9 * * *"

    @pytest.mark.asyncio
    async def test_get_schedule_not_found(self, storage):
        """Test getting a non-existent schedule."""
        retrieved = await storage.get_schedule("nonexistent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_update_schedule(self, storage):
        """Test updating a schedule."""
        spec = ScheduleSpec(cron="0 9 * * *")
        schedule = Schedule(
            schedule_id="update_test",
            workflow_name="test_workflow",
            spec=spec,
            status=ScheduleStatus.ACTIVE,
            created_at=datetime.now(UTC),
        )
        await storage.create_schedule(schedule)

        # Update the schedule
        schedule.status = ScheduleStatus.PAUSED
        schedule.updated_at = datetime.now(UTC)
        schedule.spec = ScheduleSpec(cron="0 10 * * *")
        await storage.update_schedule(schedule)

        # Verify update
        retrieved = await storage.get_schedule("update_test")
        assert retrieved.status == ScheduleStatus.PAUSED
        assert retrieved.spec.cron == "0 10 * * *"
        assert retrieved.updated_at is not None

    @pytest.mark.asyncio
    async def test_delete_schedule(self, storage):
        """Test deleting a schedule."""
        spec = ScheduleSpec(interval="5m")
        schedule = Schedule(
            schedule_id="delete_test",
            workflow_name="test_workflow",
            spec=spec,
            created_at=datetime.now(UTC),
        )
        await storage.create_schedule(schedule)

        # Verify it exists
        assert await storage.get_schedule("delete_test") is not None

        # Delete
        await storage.delete_schedule("delete_test")

        # Verify deleted (soft delete - status should be DELETED)
        retrieved = await storage.get_schedule("delete_test")
        if retrieved is not None:
            # If soft delete, status should be DELETED
            assert retrieved.status == ScheduleStatus.DELETED


class TestScheduleStorageList:
    """Test listing schedules with various filters."""

    @pytest.mark.asyncio
    async def test_list_all_schedules(self, storage):
        """Test listing all schedules."""
        now = datetime.now(UTC)

        # Create multiple schedules
        for i in range(5):
            schedule = Schedule(
                schedule_id=f"list_test_{i}",
                workflow_name=f"workflow_{i % 2}",  # 2 different workflows
                spec=ScheduleSpec(cron="0 9 * * *"),
                status=ScheduleStatus.ACTIVE if i % 2 == 0 else ScheduleStatus.PAUSED,
                created_at=now,
            )
            await storage.create_schedule(schedule)

        # List all
        schedules = await storage.list_schedules()
        assert len(schedules) == 5

    @pytest.mark.asyncio
    async def test_list_schedules_by_workflow(self, storage):
        """Test listing schedules filtered by workflow name."""
        now = datetime.now(UTC)

        # Create schedules for different workflows
        for i in range(4):
            schedule = Schedule(
                schedule_id=f"wf_filter_{i}",
                workflow_name=f"workflow_{i % 2}",
                spec=ScheduleSpec(cron="0 9 * * *"),
                created_at=now,
            )
            await storage.create_schedule(schedule)

        # Filter by workflow_0
        schedules = await storage.list_schedules(workflow_name="workflow_0")
        assert len(schedules) == 2
        for s in schedules:
            assert s.workflow_name == "workflow_0"

    @pytest.mark.asyncio
    async def test_list_schedules_by_status(self, storage):
        """Test listing schedules filtered by status."""
        now = datetime.now(UTC)

        # Create schedules with different statuses
        statuses = [
            ScheduleStatus.ACTIVE,
            ScheduleStatus.ACTIVE,
            ScheduleStatus.PAUSED,
            ScheduleStatus.DELETED,
        ]
        for i, status in enumerate(statuses):
            schedule = Schedule(
                schedule_id=f"status_filter_{i}",
                workflow_name="test_workflow",
                spec=ScheduleSpec(cron="0 9 * * *"),
                status=status,
                created_at=now,
            )
            await storage.create_schedule(schedule)

        # Filter by ACTIVE
        active = await storage.list_schedules(status=ScheduleStatus.ACTIVE)
        assert len(active) == 2

        # Filter by PAUSED
        paused = await storage.list_schedules(status=ScheduleStatus.PAUSED)
        assert len(paused) == 1

    @pytest.mark.asyncio
    async def test_list_schedules_with_limit(self, storage):
        """Test listing schedules with limit."""
        now = datetime.now(UTC)

        # Create 10 schedules
        for i in range(10):
            schedule = Schedule(
                schedule_id=f"limit_test_{i}",
                workflow_name="test_workflow",
                spec=ScheduleSpec(cron="0 9 * * *"),
                created_at=now,
            )
            await storage.create_schedule(schedule)

        # List with limit
        schedules = await storage.list_schedules(limit=5)
        assert len(schedules) == 5

    @pytest.mark.asyncio
    async def test_list_schedules_with_offset(self, storage):
        """Test listing schedules with offset."""
        now = datetime.now(UTC)

        # Create 5 schedules
        for i in range(5):
            schedule = Schedule(
                schedule_id=f"offset_test_{i:02d}",  # Zero-padded for ordering
                workflow_name="test_workflow",
                spec=ScheduleSpec(cron="0 9 * * *"),
                created_at=now + timedelta(seconds=i),  # Different timestamps
            )
            await storage.create_schedule(schedule)

        # List with offset
        schedules = await storage.list_schedules(offset=2, limit=10)
        assert len(schedules) == 3


class TestScheduleDueSchedules:
    """Test getting due schedules."""

    @pytest.mark.asyncio
    async def test_get_due_schedules(self, storage):
        """Test getting schedules that are due to run."""
        now = datetime.now(UTC)
        past = now - timedelta(minutes=5)
        future = now + timedelta(minutes=5)

        # Create schedules with different next_run_times
        for i, next_run in enumerate([past, past, future]):
            schedule = Schedule(
                schedule_id=f"due_test_{i}",
                workflow_name="test_workflow",
                spec=ScheduleSpec(cron="0 9 * * *"),
                status=ScheduleStatus.ACTIVE,
                next_run_time=next_run,
                created_at=now,
            )
            await storage.create_schedule(schedule)

        # Get due schedules
        due = await storage.get_due_schedules(now)

        # Should only get the 2 past schedules
        assert len(due) == 2
        for s in due:
            assert s.next_run_time <= now

    @pytest.mark.asyncio
    async def test_get_due_schedules_excludes_paused(self, storage):
        """Test that paused schedules are not returned as due."""
        now = datetime.now(UTC)
        past = now - timedelta(minutes=5)

        # Create active schedule
        active = Schedule(
            schedule_id="due_active",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            status=ScheduleStatus.ACTIVE,
            next_run_time=past,
            created_at=now,
        )
        await storage.create_schedule(active)

        # Create paused schedule
        paused = Schedule(
            schedule_id="due_paused",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            status=ScheduleStatus.PAUSED,
            next_run_time=past,
            created_at=now,
        )
        await storage.create_schedule(paused)

        # Get due schedules
        due = await storage.get_due_schedules(now)

        # Should only get active schedule
        assert len(due) == 1
        assert due[0].schedule_id == "due_active"


class TestScheduleRunningRuns:
    """Test managing running run IDs on schedules."""

    @pytest.mark.asyncio
    async def test_add_running_run(self, storage):
        """Test adding a running run ID to a schedule."""
        now = datetime.now(UTC)
        schedule = Schedule(
            schedule_id="running_test",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            created_at=now,
        )
        await storage.create_schedule(schedule)

        # Add running run
        await storage.add_running_run("running_test", "run_123")

        # Verify
        retrieved = await storage.get_schedule("running_test")
        assert "run_123" in retrieved.running_run_ids

    @pytest.mark.asyncio
    async def test_add_multiple_running_runs(self, storage):
        """Test adding multiple running run IDs."""
        now = datetime.now(UTC)
        schedule = Schedule(
            schedule_id="multi_run_test",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            created_at=now,
        )
        await storage.create_schedule(schedule)

        # Add multiple runs
        await storage.add_running_run("multi_run_test", "run_1")
        await storage.add_running_run("multi_run_test", "run_2")
        await storage.add_running_run("multi_run_test", "run_3")

        # Verify
        retrieved = await storage.get_schedule("multi_run_test")
        assert len(retrieved.running_run_ids) == 3

    @pytest.mark.asyncio
    async def test_remove_running_run(self, storage):
        """Test removing a running run ID from a schedule."""
        now = datetime.now(UTC)
        schedule = Schedule(
            schedule_id="remove_run_test",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            running_run_ids=["run_1", "run_2"],
            created_at=now,
        )
        await storage.create_schedule(schedule)

        # Remove a run
        await storage.remove_running_run("remove_run_test", "run_1")

        # Verify
        retrieved = await storage.get_schedule("remove_run_test")
        assert "run_1" not in retrieved.running_run_ids
        assert "run_2" in retrieved.running_run_ids

    @pytest.mark.asyncio
    async def test_remove_nonexistent_run(self, storage):
        """Test removing a run ID that doesn't exist (should not error)."""
        now = datetime.now(UTC)
        schedule = Schedule(
            schedule_id="remove_nonexistent",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            running_run_ids=["run_1"],
            created_at=now,
        )
        await storage.create_schedule(schedule)

        # Remove non-existent run (should not raise)
        await storage.remove_running_run("remove_nonexistent", "run_999")

        # Verify original run still there
        retrieved = await storage.get_schedule("remove_nonexistent")
        assert "run_1" in retrieved.running_run_ids


class TestScheduleStatistics:
    """Test schedule statistics tracking."""

    @pytest.mark.asyncio
    async def test_increment_statistics(self, storage):
        """Test incrementing schedule statistics."""
        # SQLite backend doesn't store statistics fields
        if storage.__class__.__name__ == "SQLiteStorageBackend":
            pytest.skip("SQLite backend doesn't support schedule statistics")

        now = datetime.now(UTC)
        schedule = Schedule(
            schedule_id="stats_test",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            total_runs=0,
            successful_runs=0,
            failed_runs=0,
            created_at=now,
        )
        await storage.create_schedule(schedule)

        # Simulate successful runs
        schedule = await storage.get_schedule("stats_test")
        schedule.total_runs += 1
        schedule.successful_runs += 1
        await storage.update_schedule(schedule)

        # Verify
        retrieved = await storage.get_schedule("stats_test")
        assert retrieved.total_runs == 1
        assert retrieved.successful_runs == 1
        assert retrieved.failed_runs == 0

        # Simulate failed run
        retrieved.total_runs += 1
        retrieved.failed_runs += 1
        await storage.update_schedule(retrieved)

        # Verify
        final = await storage.get_schedule("stats_test")
        assert final.total_runs == 2
        assert final.successful_runs == 1
        assert final.failed_runs == 1
