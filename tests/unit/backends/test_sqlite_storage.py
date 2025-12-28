"""
Unit tests for SQLite storage backend.

These tests verify the SQLiteStorageBackend implementation.
For integration tests with a real SQLite database, see tests/integration/.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
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
from pyworkflow.storage.sqlite import SQLiteStorageBackend


@pytest.fixture
def mock_backend(tmp_path):
    """Create a backend with mocked connection for testing."""
    backend = SQLiteStorageBackend(db_path=str(tmp_path / "test.db"))
    mock_conn = MagicMock()
    backend._db = mock_conn
    backend._initialized = True
    return backend, mock_conn


def create_mock_cursor(fetchone_result=None, fetchall_result=None):
    """Helper to create a mock cursor that works as async context manager."""
    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=fetchone_result)
    mock_cursor.fetchall = AsyncMock(return_value=fetchall_result or [])
    return mock_cursor


class TestSQLiteStorageBackendInit:
    """Test SQLiteStorageBackend initialization."""

    def test_init_with_default_path(self):
        """Test initialization with default database path."""
        backend = SQLiteStorageBackend()

        assert backend.db_path == Path("./pyworkflow_data/pyworkflow.db")
        assert backend._db is None
        assert backend._initialized is False

    def test_init_with_custom_path(self, tmp_path):
        """Test initialization with custom database path."""
        custom_path = tmp_path / "custom" / "path" / "db.sqlite"
        backend = SQLiteStorageBackend(db_path=str(custom_path))

        assert backend.db_path == custom_path
        assert backend._db is None
        assert backend._initialized is False

    def test_init_creates_parent_directory(self, tmp_path):
        """Test that initialization creates parent directories."""
        nested_path = tmp_path / "nested" / "dir" / "test.db"
        _backend = SQLiteStorageBackend(db_path=str(nested_path))  # noqa: F841

        # Parent should be created during __init__
        assert nested_path.parent.exists()


class TestSQLiteStorageBackendConnection:
    """Test connection management."""

    @pytest.mark.asyncio
    async def test_ensure_connected_raises_when_not_connected(self):
        """Test that _ensure_connected raises when connection is None."""
        backend = SQLiteStorageBackend()

        with pytest.raises(RuntimeError, match="Database not connected"):
            backend._ensure_connected()

    @pytest.mark.asyncio
    async def test_connect_creates_connection(self, tmp_path):
        """Test that connect creates a database connection."""
        backend = SQLiteStorageBackend(db_path=str(tmp_path / "test.db"))

        mock_conn = AsyncMock()

        async def mock_connect(*args, **kwargs):
            return mock_conn

        with patch("aiosqlite.connect", side_effect=mock_connect) as mock_aiosqlite:
            # Mock the schema initialization
            backend._initialize_schema = AsyncMock()

            await backend.connect()

            mock_aiosqlite.assert_called_once()
            assert backend._db is not None
            assert backend._initialized is True

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(self):
        """Test that disconnect closes the connection."""
        backend = SQLiteStorageBackend()
        mock_conn = AsyncMock()
        backend._db = mock_conn
        backend._initialized = True

        await backend.disconnect()

        mock_conn.close.assert_called_once()
        assert backend._db is None
        assert backend._initialized is False


class TestRowConversion:
    """Test row to object conversion methods."""

    def test_row_to_workflow_run(self):
        """Test converting database row to WorkflowRun."""
        backend = SQLiteStorageBackend()

        # SQLite returns tuples in column order
        row = (
            "run_123",  # 0: run_id
            "test_workflow",  # 1: workflow_name
            "running",  # 2: status
            "2024-01-01T12:00:00+00:00",  # 3: created_at
            "2024-01-01T12:00:01+00:00",  # 4: updated_at
            "2024-01-01T12:00:00+00:00",  # 5: started_at
            None,  # 6: completed_at
            "[]",  # 7: input_args
            '{"key": "value"}',  # 8: input_kwargs
            None,  # 9: result
            None,  # 10: error
            "idem_123",  # 11: idempotency_key
            "1h",  # 12: max_duration
            '{"foo": "bar"}',  # 13: metadata
            0,  # 14: recovery_attempts
            3,  # 15: max_recovery_attempts
            1,  # 16: recover_on_worker_loss (SQLite stores as int)
            None,  # 17: parent_run_id
            0,  # 18: nesting_depth
            None,  # 19: continued_from_run_id
            None,  # 20: continued_to_run_id
        )

        run = backend._row_to_workflow_run(row)

        assert run.run_id == "run_123"
        assert run.workflow_name == "test_workflow"
        assert run.status == RunStatus.RUNNING
        assert run.idempotency_key == "idem_123"
        assert run.context == {"foo": "bar"}
        assert run.recover_on_worker_loss is True

    def test_row_to_event(self):
        """Test converting database row to Event."""
        backend = SQLiteStorageBackend()

        row = (
            "event_123",  # 0: event_id
            "run_123",  # 1: run_id
            5,  # 2: sequence
            "step.completed",  # 3: type
            "2024-01-01T12:00:00+00:00",  # 4: timestamp
            '{"step_id": "step_1"}',  # 5: data
        )

        event = backend._row_to_event(row)

        assert event.event_id == "event_123"
        assert event.run_id == "run_123"
        assert event.sequence == 5
        assert event.type == EventType.STEP_COMPLETED
        assert event.data == {"step_id": "step_1"}

    def test_row_to_step_execution(self):
        """Test converting database row to StepExecution."""
        backend = SQLiteStorageBackend()

        row = (
            "step_123",  # 0: step_id
            "run_123",  # 1: run_id
            "process_data",  # 2: step_name
            "completed",  # 3: status
            "2024-01-01T12:00:00+00:00",  # 4: created_at
            "2024-01-01T12:00:01+00:00",  # 5: started_at
            "2024-01-01T12:00:05+00:00",  # 6: completed_at
            "[]",  # 7: input_args
            "{}",  # 8: input_kwargs
            '"success"',  # 9: result
            None,  # 10: error
            2,  # 11: retry_count (0-based in DB)
        )

        step = backend._row_to_step_execution(row)

        assert step.step_id == "step_123"
        assert step.step_name == "process_data"
        assert step.status == StepStatus.COMPLETED
        # retry_count 2 -> attempt 3 (1-based)
        assert step.attempt == 3

    def test_row_to_hook(self):
        """Test converting database row to Hook."""
        backend = SQLiteStorageBackend()

        row = (
            "hook_123",  # 0: hook_id
            "run_123",  # 1: run_id
            "token_abc",  # 2: token
            "2024-01-01T12:00:00+00:00",  # 3: created_at
            None,  # 4: received_at
            "2024-01-02T12:00:00+00:00",  # 5: expires_at
            "pending",  # 6: status
            None,  # 7: payload
            '{"webhook": true}',  # 8: metadata
        )

        hook = backend._row_to_hook(row)

        assert hook.hook_id == "hook_123"
        assert hook.token == "token_abc"
        assert hook.status == HookStatus.PENDING
        assert hook.metadata == {"webhook": True}

    def test_row_to_schedule(self):
        """Test converting database row to Schedule."""
        backend = SQLiteStorageBackend()

        row = (
            "sched_123",  # 0: schedule_id
            "daily_report",  # 1: workflow_name
            "0 9 * * *",  # 2: spec (cron expression)
            "cron",  # 3: spec_type
            "UTC",  # 4: timezone
            "[]",  # 5: input_args
            "{}",  # 6: input_kwargs
            "active",  # 7: status
            "skip",  # 8: overlap_policy
            "2024-01-02T09:00:00+00:00",  # 9: next_run_time
            "2024-01-01T09:00:00+00:00",  # 10: last_run_time
            '["run_1", "run_2"]',  # 11: running_run_ids
            "{}",  # 12: metadata
            "2024-01-01T00:00:00+00:00",  # 13: created_at
            "2024-01-01T09:00:00+00:00",  # 14: updated_at
            None,  # 15: paused_at
            None,  # 16: deleted_at
        )

        schedule = backend._row_to_schedule(row)

        assert schedule.schedule_id == "sched_123"
        assert schedule.workflow_name == "daily_report"
        assert schedule.spec.cron == "0 9 * * *"
        assert schedule.spec.timezone == "UTC"
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.overlap_policy == OverlapPolicy.SKIP
        assert schedule.running_run_ids == ["run_1", "run_2"]


class TestSQLiteStorageBackendConfig:
    """Test storage configuration integration."""

    def test_storage_to_config(self, tmp_path):
        """Test serializing backend to config."""
        from pyworkflow.storage.config import storage_to_config

        db_path = tmp_path / "db.sqlite"
        backend = SQLiteStorageBackend(db_path=str(db_path))
        config = storage_to_config(backend)

        assert config["type"] == "sqlite"
        # Config module serializes db_path as base_path
        assert config["base_path"] == str(db_path)

    def test_config_to_storage(self, tmp_path):
        """Test creating backend from config."""
        from pyworkflow.storage.config import config_to_storage

        db_path = tmp_path / "db.sqlite"
        # Config module uses base_path key for SQLite
        config = {"type": "sqlite", "base_path": str(db_path)}
        backend = config_to_storage(config)

        assert isinstance(backend, SQLiteStorageBackend)
        assert str(backend.db_path) == str(db_path)

    def test_storage_to_config_with_default_path(self, tmp_path):
        """Test serializing backend with default path to config."""
        from pyworkflow.storage.config import storage_to_config

        db_path = tmp_path / "default.db"
        backend = SQLiteStorageBackend(db_path=str(db_path))
        config = storage_to_config(backend)

        assert config["type"] == "sqlite"
        # Config module uses base_path key
        assert "base_path" in config

    def test_config_to_storage_with_default(self):
        """Test creating backend from minimal config."""
        from pyworkflow.storage.config import config_to_storage

        config = {"type": "sqlite"}
        backend = config_to_storage(config)

        assert isinstance(backend, SQLiteStorageBackend)


class TestWorkflowRunOperations:
    """Test workflow run CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_run(self, mock_backend):
        """Test creating a workflow run."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        run = WorkflowRun(
            run_id="run_123",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
        )

        await backend.create_run(run)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO workflow_runs" in call_args[0][0]
        assert call_args[0][1][0] == "run_123"
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_run_found(self, mock_backend):
        """Test retrieving an existing workflow run."""
        backend, mock_conn = mock_backend

        row = (
            "run_123",  # run_id
            "test_workflow",  # workflow_name
            "running",  # status
            "2024-01-01T12:00:00+00:00",  # created_at
            "2024-01-01T12:00:01+00:00",  # updated_at
            None,  # started_at
            None,  # completed_at
            "[]",  # input_args
            "{}",  # input_kwargs
            None,  # result
            None,  # error
            None,  # idempotency_key
            None,  # max_duration
            "{}",  # metadata
            0,  # recovery_attempts
            3,  # max_recovery_attempts
            1,  # recover_on_worker_loss
            None,  # parent_run_id
            0,  # nesting_depth
            None,  # continued_from_run_id
            None,  # continued_to_run_id
        )

        mock_cursor = create_mock_cursor(fetchone_result=row)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        run = await backend.get_run("run_123")

        assert run is not None
        assert run.run_id == "run_123"
        assert run.status == RunStatus.RUNNING
        mock_cursor.fetchone.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_run_not_found(self, mock_backend):
        """Test retrieving a non-existent workflow run."""
        backend, mock_conn = mock_backend

        mock_cursor = create_mock_cursor(fetchone_result=None)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        run = await backend.get_run("nonexistent")

        assert run is None

    @pytest.mark.asyncio
    async def test_get_run_by_idempotency_key(self, mock_backend):
        """Test retrieving workflow run by idempotency key."""
        backend, mock_conn = mock_backend

        row = (
            "run_123",
            "test_workflow",
            "completed",
            "2024-01-01T12:00:00+00:00",
            "2024-01-01T12:00:01+00:00",
            None,
            None,
            "[]",
            "{}",
            None,
            None,
            "idem_key_123",
            None,
            "{}",
            0,
            3,
            1,
            None,
            0,
            None,
            None,
        )

        mock_cursor = create_mock_cursor(fetchone_result=row)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        run = await backend.get_run_by_idempotency_key("idem_key_123")

        assert run is not None
        assert run.idempotency_key == "idem_key_123"

    @pytest.mark.asyncio
    async def test_update_run_status(self, mock_backend):
        """Test updating workflow run status."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        await backend.update_run_status("run_123", RunStatus.COMPLETED, result='"done"', error=None)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE workflow_runs" in call_args[0][0]
        assert "status" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_run_recovery_attempts(self, mock_backend):
        """Test updating recovery attempts counter."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        await backend.update_run_recovery_attempts("run_123", 2)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "recovery_attempts" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_runs(self, mock_backend):
        """Test listing workflow runs."""
        backend, mock_conn = mock_backend

        row = (
            "run_1",
            "test_workflow",
            "completed",
            "2024-01-01T12:00:00+00:00",
            "2024-01-01T12:00:01+00:00",
            None,
            None,
            "[]",
            "{}",
            None,
            None,
            None,
            None,
            "{}",
            0,
            3,
            1,
            None,
            0,
            None,
            None,
        )

        mock_cursor = create_mock_cursor(fetchall_result=[row])

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        runs, cursor = await backend.list_runs(limit=10)

        assert len(runs) == 1
        assert runs[0].run_id == "run_1"


class TestEventOperations:
    """Test event log operations."""

    @pytest.mark.asyncio
    async def test_record_event(self, mock_backend):
        """Test recording an event."""
        backend, mock_conn = mock_backend

        # Mock for sequence fetch - this is used with async with
        mock_cursor_seq = create_mock_cursor(fetchone_result=(0,))

        # Track which call is being made
        call_count = [0]
        execute_calls = []

        # Create a mock that works both as context manager and awaitable
        class MockExecuteResult:
            def __init__(self, cursor):
                self._cursor = cursor

            async def __aenter__(self):
                return self._cursor

            async def __aexit__(self, *args):
                pass

            def __await__(self):
                async def _noop():
                    return None

                return _noop().__await__()

        def mock_execute(sql, params=None):
            call_count[0] += 1
            execute_calls.append((sql, params))
            if "SELECT" in sql:
                return MockExecuteResult(mock_cursor_seq)
            else:
                return MockExecuteResult(AsyncMock())

        mock_conn.execute = mock_execute
        mock_conn.commit = AsyncMock()

        event = Event(
            event_id="event_123",
            run_id="run_123",
            type=EventType.WORKFLOW_STARTED,
            timestamp=datetime.now(UTC),
            data={"key": "value"},
        )

        await backend.record_event(event)

        mock_conn.commit.assert_called_once()
        # Should have called execute twice: once for SELECT, once for INSERT
        assert len(execute_calls) == 2
        assert "INSERT INTO events" in execute_calls[1][0]

    @pytest.mark.asyncio
    async def test_get_events(self, mock_backend):
        """Test retrieving events for a workflow run."""
        backend, mock_conn = mock_backend

        rows = [
            (
                "event_1",
                "run_123",
                0,
                "workflow.started",
                "2024-01-01T12:00:00+00:00",
                "{}",
            ),
            (
                "event_2",
                "run_123",
                1,
                "step.completed",
                "2024-01-01T12:00:01+00:00",
                '{"step_id": "step_1"}',
            ),
        ]

        mock_cursor = create_mock_cursor(fetchall_result=rows)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        events = await backend.get_events("run_123")

        assert len(events) == 2
        assert events[0].type == EventType.WORKFLOW_STARTED
        assert events[1].type == EventType.STEP_COMPLETED

    @pytest.mark.asyncio
    async def test_get_latest_event(self, mock_backend):
        """Test retrieving the latest event."""
        backend, mock_conn = mock_backend

        row = (
            "event_5",
            "run_123",
            5,
            "step.completed",
            "2024-01-01T12:00:05+00:00",
            "{}",
        )

        mock_cursor = create_mock_cursor(fetchone_result=row)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        event = await backend.get_latest_event("run_123")

        assert event is not None
        assert event.sequence == 5


class TestStepOperations:
    """Test step execution operations."""

    @pytest.mark.asyncio
    async def test_create_step(self, mock_backend):
        """Test creating a step execution record."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

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
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_step_found(self, mock_backend):
        """Test retrieving an existing step."""
        backend, mock_conn = mock_backend

        row = (
            "step_123",
            "run_123",
            "process_data",
            "completed",
            "2024-01-01T12:00:00+00:00",
            "2024-01-01T12:00:01+00:00",
            "2024-01-01T12:00:05+00:00",
            "[]",
            "{}",
            '"success"',
            None,
            1,  # retry_count (0-based)
        )

        mock_cursor = create_mock_cursor(fetchone_result=row)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        step = await backend.get_step("step_123")

        assert step is not None
        assert step.step_id == "step_123"
        assert step.status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_get_step_not_found(self, mock_backend):
        """Test retrieving a non-existent step."""
        backend, mock_conn = mock_backend

        mock_cursor = create_mock_cursor(fetchone_result=None)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        step = await backend.get_step("nonexistent")

        assert step is None

    @pytest.mark.asyncio
    async def test_update_step_status(self, mock_backend):
        """Test updating step execution status."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        await backend.update_step_status("step_123", StepStatus.COMPLETED, result='"done"')

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE steps" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_steps(self, mock_backend):
        """Test listing steps for a workflow run."""
        backend, mock_conn = mock_backend

        row = (
            "step_1",
            "run_123",
            "step_one",
            "completed",
            "2024-01-01T12:00:00+00:00",
            None,
            None,
            "[]",
            "{}",
            None,
            None,
            1,
        )

        mock_cursor = create_mock_cursor(fetchall_result=[row])

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        steps = await backend.list_steps("run_123")

        assert len(steps) == 1
        assert steps[0].step_id == "step_1"


class TestHookOperations:
    """Test hook operations."""

    @pytest.mark.asyncio
    async def test_create_hook(self, mock_backend):
        """Test creating a hook record."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        hook = Hook(
            hook_id="hook_123",
            run_id="run_123",
            token="token_abc",
        )

        await backend.create_hook(hook)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO hooks" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_hook_found(self, mock_backend):
        """Test retrieving an existing hook."""
        backend, mock_conn = mock_backend

        row = (
            "hook_123",
            "run_123",
            "token_abc",
            "2024-01-01T12:00:00+00:00",
            None,
            None,
            "pending",
            None,
            "{}",
        )

        mock_cursor = create_mock_cursor(fetchone_result=row)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        hook = await backend.get_hook("hook_123")

        assert hook is not None
        assert hook.hook_id == "hook_123"
        assert hook.status == HookStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_hook_not_found(self, mock_backend):
        """Test retrieving a non-existent hook."""
        backend, mock_conn = mock_backend

        mock_cursor = create_mock_cursor(fetchone_result=None)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        hook = await backend.get_hook("nonexistent")

        assert hook is None

    @pytest.mark.asyncio
    async def test_get_hook_by_token(self, mock_backend):
        """Test retrieving a hook by token."""
        backend, mock_conn = mock_backend

        row = (
            "hook_123",
            "run_123",
            "token_abc",
            "2024-01-01T12:00:00+00:00",
            None,
            None,
            "pending",
            None,
            "{}",
        )

        mock_cursor = create_mock_cursor(fetchone_result=row)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        hook = await backend.get_hook_by_token("token_abc")

        assert hook is not None
        assert hook.token == "token_abc"

    @pytest.mark.asyncio
    async def test_update_hook_status(self, mock_backend):
        """Test updating hook status."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        await backend.update_hook_status(
            "hook_123", HookStatus.RECEIVED, payload='{"data": "test"}'
        )

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE hooks" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_hooks(self, mock_backend):
        """Test listing hooks."""
        backend, mock_conn = mock_backend

        row = (
            "hook_1",
            "run_123",
            "token_1",
            "2024-01-01T12:00:00+00:00",
            None,
            None,
            "pending",
            None,
            "{}",
        )

        mock_cursor = create_mock_cursor(fetchall_result=[row])

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        hooks = await backend.list_hooks(run_id="run_123")

        assert len(hooks) == 1
        assert hooks[0].hook_id == "hook_1"


class TestCancellationOperations:
    """Test cancellation flag operations."""

    @pytest.mark.asyncio
    async def test_set_cancellation_flag(self, mock_backend):
        """Test setting a cancellation flag."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        await backend.set_cancellation_flag("run_123")

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT OR IGNORE INTO cancellation_flags" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_cancellation_flag_set(self, mock_backend):
        """Test checking a set cancellation flag."""
        backend, mock_conn = mock_backend

        mock_cursor = create_mock_cursor(fetchone_result=(1,))

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        result = await backend.check_cancellation_flag("run_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_cancellation_flag_not_set(self, mock_backend):
        """Test checking when cancellation flag is not set."""
        backend, mock_conn = mock_backend

        mock_cursor = create_mock_cursor(fetchone_result=None)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        result = await backend.check_cancellation_flag("run_123")

        assert result is False

    @pytest.mark.asyncio
    async def test_clear_cancellation_flag(self, mock_backend):
        """Test clearing a cancellation flag."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        await backend.clear_cancellation_flag("run_123")

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "DELETE FROM cancellation_flags" in call_args[0][0]
        mock_conn.commit.assert_called_once()


class TestContinueAsNewOperations:
    """Test continue-as-new chain operations."""

    @pytest.mark.asyncio
    async def test_update_run_continuation(self, mock_backend):
        """Test updating continuation link."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        await backend.update_run_continuation("run_1", "run_2")

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "continued_to_run_id" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_workflow_chain(self, mock_backend):
        """Test retrieving workflow chain."""
        backend, mock_conn = mock_backend

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
            # Mock the chain traversal query (finding first run)
            mock_cursor = create_mock_cursor(fetchone_result=None)

            @asynccontextmanager
            async def mock_execute(*args, **kwargs):
                yield mock_cursor

            mock_conn.execute = mock_execute

            runs = await backend.get_workflow_chain("run_1")

        assert len(runs) == 1


class TestChildWorkflowOperations:
    """Test child workflow operations."""

    @pytest.mark.asyncio
    async def test_get_children(self, mock_backend):
        """Test retrieving child workflows."""
        backend, mock_conn = mock_backend

        row = (
            "child_1",
            "child_workflow",
            "completed",
            "2024-01-01T12:00:00+00:00",
            "2024-01-01T12:00:01+00:00",
            None,
            None,
            "[]",
            "{}",
            None,
            None,
            None,
            None,
            "{}",
            0,
            3,
            1,
            "parent_123",
            1,
            None,
            None,
        )

        mock_cursor = create_mock_cursor(fetchall_result=[row])

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        children = await backend.get_children("parent_123")

        assert len(children) == 1
        assert children[0].parent_run_id == "parent_123"

    @pytest.mark.asyncio
    async def test_get_parent_found(self, mock_backend):
        """Test retrieving parent workflow."""
        backend, mock_conn = mock_backend

        child_row = (
            "child_1",
            "child_workflow",
            "running",
            "2024-01-01T12:00:00+00:00",
            "2024-01-01T12:00:01+00:00",
            None,
            None,
            "[]",
            "{}",
            None,
            None,
            None,
            None,
            "{}",
            0,
            3,
            1,
            "parent_123",
            1,
            None,
            None,
        )

        parent_row = (
            "parent_123",
            "parent_workflow",
            "running",
            "2024-01-01T12:00:00+00:00",
            "2024-01-01T12:00:01+00:00",
            None,
            None,
            "[]",
            "{}",
            None,
            None,
            None,
            None,
            "{}",
            0,
            3,
            1,
            None,
            0,
            None,
            None,
        )

        call_count = [0]
        rows = [child_row, parent_row]

        def create_cursor_for_call():
            mock_cursor = create_mock_cursor(fetchone_result=rows[call_count[0]])
            call_count[0] += 1
            return mock_cursor

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield create_cursor_for_call()

        mock_conn.execute = mock_execute

        parent = await backend.get_parent("child_1")

        assert parent is not None
        assert parent.run_id == "parent_123"

    @pytest.mark.asyncio
    async def test_get_parent_not_found(self, mock_backend):
        """Test get_parent when run has no parent."""
        backend, mock_conn = mock_backend

        row = (
            "run_1",
            "test_workflow",
            "running",
            "2024-01-01T12:00:00+00:00",
            "2024-01-01T12:00:01+00:00",
            None,
            None,
            "[]",
            "{}",
            None,
            None,
            None,
            None,
            "{}",
            0,
            3,
            1,
            None,  # No parent_run_id
            0,
            None,
            None,
        )

        mock_cursor = create_mock_cursor(fetchone_result=row)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        parent = await backend.get_parent("run_1")

        assert parent is None

    @pytest.mark.asyncio
    async def test_get_nesting_depth(self, mock_backend):
        """Test getting nesting depth."""
        backend, mock_conn = mock_backend

        row = (
            "run_1",
            "test_workflow",
            "running",
            "2024-01-01T12:00:00+00:00",
            "2024-01-01T12:00:01+00:00",
            None,
            None,
            "[]",
            "{}",
            None,
            None,
            None,
            None,
            "{}",
            0,
            3,
            1,
            None,
            2,  # nesting_depth
            None,
            None,
        )

        mock_cursor = create_mock_cursor(fetchone_result=row)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        depth = await backend.get_nesting_depth("run_1")

        assert depth == 2


class TestScheduleOperations:
    """Test schedule operations."""

    @pytest.mark.asyncio
    async def test_create_schedule(self, mock_backend):
        """Test creating a schedule."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        schedule = Schedule(
            schedule_id="sched_123",
            workflow_name="daily_report",
            spec=ScheduleSpec(cron="0 9 * * *"),
        )

        await backend.create_schedule(schedule)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO schedules" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_schedule_found(self, mock_backend):
        """Test retrieving an existing schedule."""
        backend, mock_conn = mock_backend

        row = (
            "sched_123",
            "daily_report",
            "0 9 * * *",
            "cron",
            "UTC",
            "[]",
            "{}",
            "active",
            "skip",
            "2024-01-02T09:00:00+00:00",
            None,
            "[]",
            "{}",
            "2024-01-01T00:00:00+00:00",
            None,
            None,
            None,
        )

        mock_cursor = create_mock_cursor(fetchone_result=row)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        schedule = await backend.get_schedule("sched_123")

        assert schedule is not None
        assert schedule.schedule_id == "sched_123"
        assert schedule.spec.cron == "0 9 * * *"

    @pytest.mark.asyncio
    async def test_get_schedule_not_found(self, mock_backend):
        """Test retrieving a non-existent schedule."""
        backend, mock_conn = mock_backend

        mock_cursor = create_mock_cursor(fetchone_result=None)

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        schedule = await backend.get_schedule("nonexistent")

        assert schedule is None

    @pytest.mark.asyncio
    async def test_update_schedule(self, mock_backend):
        """Test updating a schedule."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        schedule = Schedule(
            schedule_id="sched_123",
            workflow_name="daily_report",
            spec=ScheduleSpec(cron="0 10 * * *"),
        )

        await backend.update_schedule(schedule)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE schedules" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_schedule(self, mock_backend):
        """Test deleting (soft delete) a schedule."""
        backend, mock_conn = mock_backend
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()

        await backend.delete_schedule("sched_123")

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE schedules" in call_args[0][0]
        assert "deleted_at" in call_args[0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_schedules(self, mock_backend):
        """Test listing schedules."""
        backend, mock_conn = mock_backend

        row = (
            "sched_1",
            "daily_report",
            "0 9 * * *",
            "cron",
            "UTC",
            "[]",
            "{}",
            "active",
            "skip",
            "2024-01-02T09:00:00+00:00",
            None,
            "[]",
            "{}",
            "2024-01-01T00:00:00+00:00",
            None,
            None,
            None,
        )

        mock_cursor = create_mock_cursor(fetchall_result=[row])

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        schedules = await backend.list_schedules()

        assert len(schedules) == 1
        assert schedules[0].schedule_id == "sched_1"

    @pytest.mark.asyncio
    async def test_get_due_schedules(self, mock_backend):
        """Test getting schedules that are due to run."""
        backend, mock_conn = mock_backend

        row = (
            "sched_1",
            "daily_report",
            "0 9 * * *",
            "cron",
            "UTC",
            "[]",
            "{}",
            "active",
            "skip",
            "2024-01-01T09:00:00+00:00",
            None,
            "[]",
            "{}",
            "2024-01-01T00:00:00+00:00",
            None,
            None,
            None,
        )

        mock_cursor = create_mock_cursor(fetchall_result=[row])

        @asynccontextmanager
        async def mock_execute(*args, **kwargs):
            yield mock_cursor

        mock_conn.execute = mock_execute

        now = datetime(2024, 1, 1, 9, 1, 0, tzinfo=UTC)
        schedules = await backend.get_due_schedules(now)

        assert len(schedules) == 1

    @pytest.mark.asyncio
    async def test_add_running_run(self, mock_backend):
        """Test adding a run_id to schedule's running_run_ids."""
        backend, mock_conn = mock_backend

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
            updated_schedule = mock_update.call_args[0][0]
            assert "run_2" in updated_schedule.running_run_ids

    @pytest.mark.asyncio
    async def test_remove_running_run(self, mock_backend):
        """Test removing a run_id from schedule's running_run_ids."""
        backend, mock_conn = mock_backend

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
            updated_schedule = mock_update.call_args[0][0]
            assert "run_1" not in updated_schedule.running_run_ids
            assert "run_2" in updated_schedule.running_run_ids
