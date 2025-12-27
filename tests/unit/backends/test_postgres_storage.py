"""
Unit tests for PostgreSQL storage backend.

These tests verify the PostgresStorageBackend implementation.
For integration tests with a real PostgreSQL database, see tests/integration/.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyworkflow.engine.events import EventType
from pyworkflow.storage.schemas import (
    HookStatus,
    OverlapPolicy,
    RunStatus,
    ScheduleStatus,
    StepStatus,
)

# Skip all tests if asyncpg is not installed
pytest.importorskip("asyncpg")

from pyworkflow.storage.postgres import PostgresStorageBackend


class TestPostgresStorageBackendInit:
    """Test PostgresStorageBackend initialization."""

    def test_init_with_dsn(self):
        """Test initialization with DSN connection string."""
        dsn = "postgresql://user:pass@localhost:5432/db"
        backend = PostgresStorageBackend(dsn=dsn)

        assert backend.dsn == dsn
        assert backend._pool is None
        assert backend._initialized is False

    def test_init_with_individual_params(self):
        """Test initialization with individual connection parameters."""
        backend = PostgresStorageBackend(
            host="db.example.com",
            port=5433,
            user="testuser",
            password="testpass",
            database="testdb",
        )

        assert backend.dsn is None
        assert backend.host == "db.example.com"
        assert backend.port == 5433
        assert backend.user == "testuser"
        assert backend.password == "testpass"
        assert backend.database == "testdb"

    def test_init_with_pool_settings(self):
        """Test initialization with custom pool settings."""
        backend = PostgresStorageBackend(
            min_pool_size=5,
            max_pool_size=20,
        )

        assert backend.min_pool_size == 5
        assert backend.max_pool_size == 20

    def test_build_dsn_with_password(self):
        """Test DSN building with password."""
        backend = PostgresStorageBackend(
            host="localhost",
            port=5432,
            user="myuser",
            password="mypass",
            database="mydb",
        )

        dsn = backend._build_dsn()
        assert dsn == "postgresql://myuser:mypass@localhost:5432/mydb"

    def test_build_dsn_without_password(self):
        """Test DSN building without password."""
        backend = PostgresStorageBackend(
            host="localhost",
            port=5432,
            user="myuser",
            password="",
            database="mydb",
        )

        dsn = backend._build_dsn()
        assert dsn == "postgresql://myuser@localhost:5432/mydb"


class TestPostgresStorageBackendConnection:
    """Test connection management."""

    @pytest.mark.asyncio
    async def test_ensure_connected_raises_when_not_connected(self):
        """Test that _ensure_connected raises when pool is None."""
        backend = PostgresStorageBackend()

        with pytest.raises(RuntimeError, match="Database not connected"):
            backend._ensure_connected()

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self):
        """Test that connect creates a connection pool."""
        backend = PostgresStorageBackend(dsn="postgresql://test@localhost/test")

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock())

        async def mock_create_pool(*args, **kwargs):
            return mock_pool

        with patch("asyncpg.create_pool", side_effect=mock_create_pool) as mock_create:
            # Mock the schema initialization
            backend._initialize_schema = AsyncMock()

            await backend.connect()

            mock_create.assert_called_once()
            assert backend._pool is not None
            assert backend._initialized is True

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self):
        """Test that disconnect closes the connection pool."""
        backend = PostgresStorageBackend()
        mock_pool = AsyncMock()
        backend._pool = mock_pool
        backend._initialized = True

        await backend.disconnect()

        mock_pool.close.assert_called_once()
        assert backend._pool is None
        assert backend._initialized is False


class TestRowConversion:
    """Test row to object conversion methods."""

    def test_row_to_workflow_run(self):
        """Test converting database row to WorkflowRun."""
        backend = PostgresStorageBackend()

        # Create a mock record that behaves like asyncpg.Record
        row = {
            "run_id": "run_123",
            "workflow_name": "test_workflow",
            "status": "running",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "updated_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            "started_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "completed_at": None,
            "input_args": "[]",
            "input_kwargs": '{"key": "value"}',
            "result": None,
            "error": None,
            "idempotency_key": "idem_123",
            "max_duration": "1h",
            "metadata": '{"foo": "bar"}',
            "recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "recover_on_worker_loss": True,
            "parent_run_id": None,
            "nesting_depth": 0,
            "continued_from_run_id": None,
            "continued_to_run_id": None,
        }

        run = backend._row_to_workflow_run(row)

        assert run.run_id == "run_123"
        assert run.workflow_name == "test_workflow"
        assert run.status == RunStatus.RUNNING
        assert run.idempotency_key == "idem_123"
        assert run.metadata == {"foo": "bar"}
        assert run.recover_on_worker_loss is True

    def test_row_to_event(self):
        """Test converting database row to Event."""
        backend = PostgresStorageBackend()

        row = {
            "event_id": "event_123",
            "run_id": "run_123",
            "sequence": 5,
            "type": "step.completed",
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "data": '{"step_id": "step_1"}',
        }

        event = backend._row_to_event(row)

        assert event.event_id == "event_123"
        assert event.run_id == "run_123"
        assert event.sequence == 5
        assert event.type == EventType.STEP_COMPLETED
        assert event.data == {"step_id": "step_1"}

    def test_row_to_step_execution(self):
        """Test converting database row to StepExecution."""
        backend = PostgresStorageBackend()

        row = {
            "step_id": "step_123",
            "run_id": "run_123",
            "step_name": "process_data",
            "status": "completed",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "started_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            "completed_at": datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC),
            "input_args": "[]",
            "input_kwargs": "{}",
            "result": '"success"',
            "error": None,
            "retry_count": 2,
        }

        step = backend._row_to_step_execution(row)

        assert step.step_id == "step_123"
        assert step.step_name == "process_data"
        assert step.status == StepStatus.COMPLETED
        assert step.attempt == 2

    def test_row_to_hook(self):
        """Test converting database row to Hook."""
        backend = PostgresStorageBackend()

        row = {
            "hook_id": "hook_123",
            "run_id": "run_123",
            "token": "token_abc",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "received_at": None,
            "expires_at": datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
            "status": "pending",
            "payload": None,
            "metadata": '{"webhook": true}',
        }

        hook = backend._row_to_hook(row)

        assert hook.hook_id == "hook_123"
        assert hook.token == "token_abc"
        assert hook.status == HookStatus.PENDING
        assert hook.metadata == {"webhook": True}

    def test_row_to_schedule(self):
        """Test converting database row to Schedule."""
        backend = PostgresStorageBackend()

        row = {
            "schedule_id": "sched_123",
            "workflow_name": "daily_report",
            "spec": '{"cron": "0 9 * * *", "timezone": "UTC"}',
            "spec_type": "cron",
            "timezone": "UTC",
            "input_args": "[]",
            "input_kwargs": "{}",
            "status": "active",
            "overlap_policy": "skip",
            "next_run_time": datetime(2024, 1, 2, 9, 0, 0, tzinfo=UTC),
            "last_run_time": datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC),
            "running_run_ids": '["run_1", "run_2"]',
            "metadata": "{}",
            "created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
            "updated_at": datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC),
            "paused_at": None,
            "deleted_at": None,
        }

        schedule = backend._row_to_schedule(row)

        assert schedule.schedule_id == "sched_123"
        assert schedule.workflow_name == "daily_report"
        assert schedule.spec.cron == "0 9 * * *"
        assert schedule.spec.timezone == "UTC"
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.overlap_policy == OverlapPolicy.SKIP
        assert schedule.running_run_ids == ["run_1", "run_2"]


class TestPostgresStorageBackendConfig:
    """Test storage configuration integration."""

    def test_storage_to_config_with_dsn(self):
        """Test serializing backend with DSN to config."""
        from pyworkflow.storage.config import storage_to_config

        backend = PostgresStorageBackend(dsn="postgresql://user:pass@host:5432/db")
        config = storage_to_config(backend)

        assert config["type"] == "postgres"
        assert config["dsn"] == "postgresql://user:pass@host:5432/db"

    def test_storage_to_config_with_params(self):
        """Test serializing backend with params to config."""
        from pyworkflow.storage.config import storage_to_config

        backend = PostgresStorageBackend(
            host="db.example.com",
            port=5433,
            user="testuser",
            password="testpass",
            database="testdb",
        )
        config = storage_to_config(backend)

        assert config["type"] == "postgres"
        assert config["host"] == "db.example.com"
        assert config["port"] == 5433
        assert config["user"] == "testuser"
        assert config["password"] == "testpass"
        assert config["database"] == "testdb"

    def test_config_to_storage_with_dsn(self):
        """Test creating backend from config with DSN."""
        from pyworkflow.storage.config import config_to_storage

        config = {"type": "postgres", "dsn": "postgresql://user:pass@host:5432/db"}
        backend = config_to_storage(config)

        assert isinstance(backend, PostgresStorageBackend)
        assert backend.dsn == "postgresql://user:pass@host:5432/db"

    def test_config_to_storage_with_params(self):
        """Test creating backend from config with params."""
        from pyworkflow.storage.config import config_to_storage

        config = {
            "type": "postgres",
            "host": "db.example.com",
            "port": 5433,
            "user": "testuser",
            "password": "testpass",
            "database": "testdb",
        }
        backend = config_to_storage(config)

        assert isinstance(backend, PostgresStorageBackend)
        assert backend.host == "db.example.com"
        assert backend.port == 5433
        assert backend.user == "testuser"
        assert backend.password == "testpass"
        assert backend.database == "testdb"
