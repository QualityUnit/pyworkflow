"""
Unit tests for PostgreSQL storage backend.

These tests verify the PostgresStorageBackend implementation.
For integration tests with a real PostgreSQL database, see tests/integration/.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyworkflow.engine.events import Event, EventType
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

# Skip all tests if asyncpg is not installed
pytest.importorskip("asyncpg")

from pyworkflow.storage.postgres import PostgresStorageBackend


@pytest.fixture
def mock_backend():
    """Create a backend with mocked pool for testing."""
    backend = PostgresStorageBackend()
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    # Make pool.acquire() work as async context manager
    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_pool.acquire = mock_acquire
    backend._pool = mock_pool
    return backend, mock_conn


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
        assert run.context == {"foo": "bar"}
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


class TestWorkflowRunOperations:
    """Test workflow run CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_run(self, mock_backend):
        """Test creating a workflow run."""
        backend, mock_conn = mock_backend

        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
        )

        await backend.create_run(run)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO workflow_runs" in call_args[0][0]
        assert call_args[0][1] == "run_123"

    @pytest.mark.asyncio
    async def test_get_run_found(self, mock_backend):
        """Test retrieving an existing workflow run."""
        backend, mock_conn = mock_backend

        mock_conn.fetchrow.return_value = {
            "run_id": "run_123",
            "workflow_name": "test_workflow",
            "status": "running",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "updated_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            "started_at": None,
            "completed_at": None,
            "input_args": "[]",
            "input_kwargs": "{}",
            "result": None,
            "error": None,
            "idempotency_key": None,
            "max_duration": None,
            "metadata": "{}",
            "recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "recover_on_worker_loss": True,
            "parent_run_id": None,
            "nesting_depth": 0,
            "continued_from_run_id": None,
            "continued_to_run_id": None,
        }

        run = await backend.get_run("run_123")

        assert run is not None
        assert run.run_id == "run_123"
        assert run.status == RunStatus.RUNNING
        mock_conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_run_not_found(self, mock_backend):
        """Test retrieving a non-existent workflow run."""
        backend, mock_conn = mock_backend
        mock_conn.fetchrow.return_value = None

        run = await backend.get_run("nonexistent")

        assert run is None

    @pytest.mark.asyncio
    async def test_get_run_by_idempotency_key(self, mock_backend):
        """Test retrieving workflow run by idempotency key."""
        backend, mock_conn = mock_backend

        mock_conn.fetchrow.return_value = {
            "run_id": "run_123",
            "workflow_name": "test_workflow",
            "status": "completed",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "updated_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            "started_at": None,
            "completed_at": None,
            "input_args": "[]",
            "input_kwargs": "{}",
            "result": None,
            "error": None,
            "idempotency_key": "idem_key_123",
            "max_duration": None,
            "metadata": "{}",
            "recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "recover_on_worker_loss": True,
            "parent_run_id": None,
            "nesting_depth": 0,
            "continued_from_run_id": None,
            "continued_to_run_id": None,
        }

        run = await backend.get_run_by_idempotency_key("idem_key_123")

        assert run is not None
        assert run.idempotency_key == "idem_key_123"

    @pytest.mark.asyncio
    async def test_update_run_status(self, mock_backend):
        """Test updating workflow run status."""
        backend, mock_conn = mock_backend

        await backend.update_run_status("run_123", RunStatus.COMPLETED, result='"done"', error=None)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE workflow_runs" in call_args[0][0]
        assert "status" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_update_run_recovery_attempts(self, mock_backend):
        """Test updating recovery attempts counter."""
        backend, mock_conn = mock_backend

        await backend.update_run_recovery_attempts("run_123", 2)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "recovery_attempts" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_runs(self, mock_backend):
        """Test listing workflow runs."""
        backend, mock_conn = mock_backend

        mock_conn.fetch.return_value = [
            {
                "run_id": "run_1",
                "workflow_name": "test_workflow",
                "status": "completed",
                "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "updated_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
                "started_at": None,
                "completed_at": None,
                "input_args": "[]",
                "input_kwargs": "{}",
                "result": None,
                "error": None,
                "idempotency_key": None,
                "max_duration": None,
                "metadata": "{}",
                "recovery_attempts": 0,
                "max_recovery_attempts": 3,
                "recover_on_worker_loss": True,
                "parent_run_id": None,
                "nesting_depth": 0,
                "continued_from_run_id": None,
                "continued_to_run_id": None,
            }
        ]

        runs, cursor = await backend.list_runs(limit=10)

        assert len(runs) == 1
        assert runs[0].run_id == "run_1"


class TestEventOperations:
    """Test event log operations."""

    @pytest.mark.asyncio
    async def test_record_event(self, mock_backend):
        """Test recording an event."""
        backend, mock_conn = mock_backend

        # Mock the sequence fetch
        mock_conn.fetchrow.return_value = [0]

        # Mock transaction context manager
        @asynccontextmanager
        async def mock_transaction():
            yield

        mock_conn.transaction = mock_transaction

        event = Event(
            event_id="event_123",
            run_id="run_123",
            type=EventType.WORKFLOW_STARTED,
            timestamp=datetime.now(UTC),
            data={"key": "value"},
        )

        await backend.record_event(event)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO events" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_events(self, mock_backend):
        """Test retrieving events for a workflow run."""
        backend, mock_conn = mock_backend

        mock_conn.fetch.return_value = [
            {
                "event_id": "event_1",
                "run_id": "run_123",
                "sequence": 0,
                "type": "workflow.started",
                "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "data": "{}",
            },
            {
                "event_id": "event_2",
                "run_id": "run_123",
                "sequence": 1,
                "type": "step.completed",
                "timestamp": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
                "data": '{"step_id": "step_1"}',
            },
        ]

        events = await backend.get_events("run_123")

        assert len(events) == 2
        assert events[0].type == EventType.WORKFLOW_STARTED
        assert events[1].type == EventType.STEP_COMPLETED

    @pytest.mark.asyncio
    async def test_get_latest_event(self, mock_backend):
        """Test retrieving the latest event."""
        backend, mock_conn = mock_backend

        mock_conn.fetchrow.return_value = {
            "event_id": "event_5",
            "run_id": "run_123",
            "sequence": 5,
            "type": "step.completed",
            "timestamp": datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC),
            "data": "{}",
        }

        event = await backend.get_latest_event("run_123")

        assert event is not None
        assert event.sequence == 5


class TestStepOperations:
    """Test step execution operations."""

    @pytest.mark.asyncio
    async def test_create_step(self, mock_backend):
        """Test creating a step execution record."""
        backend, mock_conn = mock_backend

        step = StepExecution(
            step_id="step_123",
            run_id="run_123",
            step_name="process_data",
            status=StepStatus.PENDING,
        )

        await backend.create_step(step)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO steps" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_step_found(self, mock_backend):
        """Test retrieving an existing step."""
        backend, mock_conn = mock_backend

        mock_conn.fetchrow.return_value = {
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
            "retry_count": 1,
        }

        step = await backend.get_step("step_123")

        assert step is not None
        assert step.step_id == "step_123"
        assert step.status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_get_step_not_found(self, mock_backend):
        """Test retrieving a non-existent step."""
        backend, mock_conn = mock_backend
        mock_conn.fetchrow.return_value = None

        step = await backend.get_step("nonexistent")

        assert step is None

    @pytest.mark.asyncio
    async def test_update_step_status(self, mock_backend):
        """Test updating step execution status."""
        backend, mock_conn = mock_backend

        await backend.update_step_status("step_123", StepStatus.COMPLETED, result='"done"')

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE steps" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_steps(self, mock_backend):
        """Test listing steps for a workflow run."""
        backend, mock_conn = mock_backend

        mock_conn.fetch.return_value = [
            {
                "step_id": "step_1",
                "run_id": "run_123",
                "step_name": "step_one",
                "status": "completed",
                "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "started_at": None,
                "completed_at": None,
                "input_args": "[]",
                "input_kwargs": "{}",
                "result": None,
                "error": None,
                "retry_count": 1,
            }
        ]

        steps = await backend.list_steps("run_123")

        assert len(steps) == 1
        assert steps[0].step_id == "step_1"


class TestHookOperations:
    """Test hook operations."""

    @pytest.mark.asyncio
    async def test_create_hook(self, mock_backend):
        """Test creating a hook record."""
        backend, mock_conn = mock_backend

        hook = Hook(
            hook_id="hook_123",
            run_id="run_123",
            token="token_abc",
        )

        await backend.create_hook(hook)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO hooks" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_hook_found(self, mock_backend):
        """Test retrieving an existing hook."""
        backend, mock_conn = mock_backend

        mock_conn.fetchrow.return_value = {
            "hook_id": "hook_123",
            "run_id": "run_123",
            "token": "token_abc",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "received_at": None,
            "expires_at": None,
            "status": "pending",
            "payload": None,
            "metadata": "{}",
        }

        hook = await backend.get_hook("hook_123")

        assert hook is not None
        assert hook.hook_id == "hook_123"
        assert hook.status == HookStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_hook_not_found(self, mock_backend):
        """Test retrieving a non-existent hook."""
        backend, mock_conn = mock_backend
        mock_conn.fetchrow.return_value = None

        hook = await backend.get_hook("nonexistent")

        assert hook is None

    @pytest.mark.asyncio
    async def test_get_hook_by_token(self, mock_backend):
        """Test retrieving a hook by token."""
        backend, mock_conn = mock_backend

        mock_conn.fetchrow.return_value = {
            "hook_id": "hook_123",
            "run_id": "run_123",
            "token": "token_abc",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "received_at": None,
            "expires_at": None,
            "status": "pending",
            "payload": None,
            "metadata": "{}",
        }

        hook = await backend.get_hook_by_token("token_abc")

        assert hook is not None
        assert hook.token == "token_abc"

    @pytest.mark.asyncio
    async def test_update_hook_status(self, mock_backend):
        """Test updating hook status."""
        backend, mock_conn = mock_backend

        await backend.update_hook_status(
            "hook_123", HookStatus.RECEIVED, payload='{"data": "test"}'
        )

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE hooks" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_hooks(self, mock_backend):
        """Test listing hooks."""
        backend, mock_conn = mock_backend

        mock_conn.fetch.return_value = [
            {
                "hook_id": "hook_1",
                "run_id": "run_123",
                "token": "token_1",
                "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "received_at": None,
                "expires_at": None,
                "status": "pending",
                "payload": None,
                "metadata": "{}",
            }
        ]

        hooks = await backend.list_hooks(run_id="run_123")

        assert len(hooks) == 1
        assert hooks[0].hook_id == "hook_1"


class TestCancellationOperations:
    """Test cancellation flag operations."""

    @pytest.mark.asyncio
    async def test_set_cancellation_flag(self, mock_backend):
        """Test setting a cancellation flag."""
        backend, mock_conn = mock_backend

        await backend.set_cancellation_flag("run_123")

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO cancellation_flags" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_check_cancellation_flag_set(self, mock_backend):
        """Test checking a set cancellation flag."""
        backend, mock_conn = mock_backend
        mock_conn.fetchrow.return_value = [1]  # Row exists

        result = await backend.check_cancellation_flag("run_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_cancellation_flag_not_set(self, mock_backend):
        """Test checking when cancellation flag is not set."""
        backend, mock_conn = mock_backend
        mock_conn.fetchrow.return_value = None

        result = await backend.check_cancellation_flag("run_123")

        assert result is False

    @pytest.mark.asyncio
    async def test_clear_cancellation_flag(self, mock_backend):
        """Test clearing a cancellation flag."""
        backend, mock_conn = mock_backend

        await backend.clear_cancellation_flag("run_123")

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "DELETE FROM cancellation_flags" in call_args[0][0]


class TestContinueAsNewOperations:
    """Test continue-as-new chain operations."""

    @pytest.mark.asyncio
    async def test_update_run_continuation(self, mock_backend):
        """Test updating continuation link."""
        backend, mock_conn = mock_backend

        await backend.update_run_continuation("run_1", "run_2")

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "continued_to_run_id" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_workflow_chain(self, mock_backend):
        """Test retrieving workflow chain."""
        backend, mock_conn = mock_backend

        # First call finds the start of chain
        mock_conn.fetchrow.side_effect = [
            None,  # No continued_from_run_id (this is the start)
        ]

        # Mock get_run for chain traversal
        with patch.object(
            backend,
            "get_run",
            return_value=WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                continued_to_run_id=None,
            ),
        ):
            runs = await backend.get_workflow_chain("run_1")

        assert len(runs) == 1


class TestChildWorkflowOperations:
    """Test child workflow operations."""

    @pytest.mark.asyncio
    async def test_get_children(self, mock_backend):
        """Test retrieving child workflows."""
        backend, mock_conn = mock_backend

        mock_conn.fetch.return_value = [
            {
                "run_id": "child_1",
                "workflow_name": "child_workflow",
                "status": "completed",
                "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "updated_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
                "started_at": None,
                "completed_at": None,
                "input_args": "[]",
                "input_kwargs": "{}",
                "result": None,
                "error": None,
                "idempotency_key": None,
                "max_duration": None,
                "metadata": "{}",
                "recovery_attempts": 0,
                "max_recovery_attempts": 3,
                "recover_on_worker_loss": True,
                "parent_run_id": "parent_123",
                "nesting_depth": 1,
                "continued_from_run_id": None,
                "continued_to_run_id": None,
            }
        ]

        children = await backend.get_children("parent_123")

        assert len(children) == 1
        assert children[0].parent_run_id == "parent_123"

    @pytest.mark.asyncio
    async def test_get_parent_found(self, mock_backend):
        """Test retrieving parent workflow."""
        backend, mock_conn = mock_backend

        # First call gets the child run
        child_data = {
            "run_id": "child_1",
            "workflow_name": "child_workflow",
            "status": "running",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "updated_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            "started_at": None,
            "completed_at": None,
            "input_args": "[]",
            "input_kwargs": "{}",
            "result": None,
            "error": None,
            "idempotency_key": None,
            "max_duration": None,
            "metadata": "{}",
            "recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "recover_on_worker_loss": True,
            "parent_run_id": "parent_123",
            "nesting_depth": 1,
            "continued_from_run_id": None,
            "continued_to_run_id": None,
        }

        parent_data = {
            "run_id": "parent_123",
            "workflow_name": "parent_workflow",
            "status": "running",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "updated_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            "started_at": None,
            "completed_at": None,
            "input_args": "[]",
            "input_kwargs": "{}",
            "result": None,
            "error": None,
            "idempotency_key": None,
            "max_duration": None,
            "metadata": "{}",
            "recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "recover_on_worker_loss": True,
            "parent_run_id": None,
            "nesting_depth": 0,
            "continued_from_run_id": None,
            "continued_to_run_id": None,
        }

        mock_conn.fetchrow.side_effect = [child_data, parent_data]

        parent = await backend.get_parent("child_1")

        assert parent is not None
        assert parent.run_id == "parent_123"

    @pytest.mark.asyncio
    async def test_get_parent_not_found(self, mock_backend):
        """Test get_parent when run has no parent."""
        backend, mock_conn = mock_backend

        mock_conn.fetchrow.return_value = {
            "run_id": "run_1",
            "workflow_name": "test_workflow",
            "status": "running",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "updated_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            "started_at": None,
            "completed_at": None,
            "input_args": "[]",
            "input_kwargs": "{}",
            "result": None,
            "error": None,
            "idempotency_key": None,
            "max_duration": None,
            "metadata": "{}",
            "recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "recover_on_worker_loss": True,
            "parent_run_id": None,
            "nesting_depth": 0,
            "continued_from_run_id": None,
            "continued_to_run_id": None,
        }

        parent = await backend.get_parent("run_1")

        assert parent is None

    @pytest.mark.asyncio
    async def test_get_nesting_depth(self, mock_backend):
        """Test getting nesting depth."""
        backend, mock_conn = mock_backend

        mock_conn.fetchrow.return_value = {
            "run_id": "run_1",
            "workflow_name": "test_workflow",
            "status": "running",
            "created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            "updated_at": datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            "started_at": None,
            "completed_at": None,
            "input_args": "[]",
            "input_kwargs": "{}",
            "result": None,
            "error": None,
            "idempotency_key": None,
            "max_duration": None,
            "metadata": "{}",
            "recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "recover_on_worker_loss": True,
            "parent_run_id": None,
            "nesting_depth": 2,
            "continued_from_run_id": None,
            "continued_to_run_id": None,
        }

        depth = await backend.get_nesting_depth("run_1")

        assert depth == 2


class TestScheduleOperations:
    """Test schedule operations."""

    @pytest.mark.asyncio
    async def test_create_schedule(self, mock_backend):
        """Test creating a schedule."""
        backend, mock_conn = mock_backend

        schedule = Schedule(
            schedule_id="sched_123",
            workflow_name="daily_report",
            spec=ScheduleSpec(cron="0 9 * * *"),
        )

        await backend.create_schedule(schedule)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO schedules" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_schedule_found(self, mock_backend):
        """Test retrieving an existing schedule."""
        backend, mock_conn = mock_backend

        mock_conn.fetchrow.return_value = {
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
            "last_run_time": None,
            "running_run_ids": "[]",
            "metadata": "{}",
            "created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
            "updated_at": None,
            "paused_at": None,
            "deleted_at": None,
        }

        schedule = await backend.get_schedule("sched_123")

        assert schedule is not None
        assert schedule.schedule_id == "sched_123"
        assert schedule.spec.cron == "0 9 * * *"

    @pytest.mark.asyncio
    async def test_get_schedule_not_found(self, mock_backend):
        """Test retrieving a non-existent schedule."""
        backend, mock_conn = mock_backend
        mock_conn.fetchrow.return_value = None

        schedule = await backend.get_schedule("nonexistent")

        assert schedule is None

    @pytest.mark.asyncio
    async def test_update_schedule(self, mock_backend):
        """Test updating a schedule."""
        backend, mock_conn = mock_backend

        schedule = Schedule(
            schedule_id="sched_123",
            workflow_name="daily_report",
            spec=ScheduleSpec(cron="0 10 * * *"),
        )

        await backend.update_schedule(schedule)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE schedules" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_delete_schedule(self, mock_backend):
        """Test deleting (soft delete) a schedule."""
        backend, mock_conn = mock_backend

        await backend.delete_schedule("sched_123")

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE schedules" in call_args[0][0]
        assert "deleted_at" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_schedules(self, mock_backend):
        """Test listing schedules."""
        backend, mock_conn = mock_backend

        mock_conn.fetch.return_value = [
            {
                "schedule_id": "sched_1",
                "workflow_name": "daily_report",
                "spec": '{"cron": "0 9 * * *", "timezone": "UTC"}',
                "spec_type": "cron",
                "timezone": "UTC",
                "input_args": "[]",
                "input_kwargs": "{}",
                "status": "active",
                "overlap_policy": "skip",
                "next_run_time": datetime(2024, 1, 2, 9, 0, 0, tzinfo=UTC),
                "last_run_time": None,
                "running_run_ids": "[]",
                "metadata": "{}",
                "created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
                "updated_at": None,
                "paused_at": None,
                "deleted_at": None,
            }
        ]

        schedules = await backend.list_schedules()

        assert len(schedules) == 1
        assert schedules[0].schedule_id == "sched_1"

    @pytest.mark.asyncio
    async def test_get_due_schedules(self, mock_backend):
        """Test getting schedules that are due to run."""
        backend, mock_conn = mock_backend

        mock_conn.fetch.return_value = [
            {
                "schedule_id": "sched_1",
                "workflow_name": "daily_report",
                "spec": '{"cron": "0 9 * * *", "timezone": "UTC"}',
                "spec_type": "cron",
                "timezone": "UTC",
                "input_args": "[]",
                "input_kwargs": "{}",
                "status": "active",
                "overlap_policy": "skip",
                "next_run_time": datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC),
                "last_run_time": None,
                "running_run_ids": "[]",
                "metadata": "{}",
                "created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
                "updated_at": None,
                "paused_at": None,
                "deleted_at": None,
            }
        ]

        now = datetime(2024, 1, 1, 9, 1, 0, tzinfo=UTC)
        schedules = await backend.get_due_schedules(now)

        assert len(schedules) == 1

    @pytest.mark.asyncio
    async def test_add_running_run(self, mock_backend):
        """Test adding a run_id to schedule's running_run_ids."""
        backend, mock_conn = mock_backend

        # Mock get_schedule to return a schedule
        schedule = Schedule(
            schedule_id="sched_123",
            workflow_name="daily_report",
            spec=ScheduleSpec(cron="0 9 * * *"),
            running_run_ids=["run_1"],
        )

        with (
            patch.object(backend, "get_schedule", return_value=schedule),
            patch.object(backend, "update_schedule") as mock_update,
        ):
            await backend.add_running_run("sched_123", "run_2")

            mock_update.assert_called_once()
            # Verify run_2 was added
            updated_schedule = mock_update.call_args[0][0]
            assert "run_2" in updated_schedule.running_run_ids

    @pytest.mark.asyncio
    async def test_remove_running_run(self, mock_backend):
        """Test removing a run_id from schedule's running_run_ids."""
        backend, mock_conn = mock_backend

        # Mock get_schedule to return a schedule
        schedule = Schedule(
            schedule_id="sched_123",
            workflow_name="daily_report",
            spec=ScheduleSpec(cron="0 9 * * *"),
            running_run_ids=["run_1", "run_2"],
        )

        with (
            patch.object(backend, "get_schedule", return_value=schedule),
            patch.object(backend, "update_schedule") as mock_update,
        ):
            await backend.remove_running_run("sched_123", "run_1")

            mock_update.assert_called_once()
            # Verify run_1 was removed
            updated_schedule = mock_update.call_args[0][0]
            assert "run_1" not in updated_schedule.running_run_ids
            assert "run_2" in updated_schedule.running_run_ids
