"""
Unit tests for Cassandra storage backend.

These tests verify the CassandraStorageBackend implementation using mocks.
For integration tests with a real Cassandra database, see tests/integration/.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

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

# Skip all tests if cassandra-driver is not installed
pytest.importorskip("cassandra")

from pyworkflow.storage.cassandra import CassandraStorageBackend


@pytest.fixture
def mock_session():
    """Create a mock Cassandra session."""
    return MagicMock()


@pytest.fixture
def mock_cluster():
    """Create a mock Cassandra cluster."""
    return MagicMock()


@pytest.fixture
def mock_backend(mock_session, mock_cluster):
    """Create a backend with mocked session for testing."""
    backend = CassandraStorageBackend()
    backend._session = mock_session
    backend._cluster = mock_cluster
    backend._initialized = True
    return backend


class TestCassandraStorageBackendInit:
    """Test Cassandra backend initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        backend = CassandraStorageBackend()

        assert backend.contact_points == ["localhost"]
        assert backend.port == 9042
        assert backend.keyspace == "pyworkflow"
        assert backend.username is None
        assert backend.password is None
        assert backend._initialized is False

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        backend = CassandraStorageBackend(
            contact_points=["cassandra-1", "cassandra-2"],
            port=9043,
            keyspace="custom_keyspace",
            username="testuser",
            password="testpass",
            read_consistency="LOCAL_ONE",
            write_consistency="LOCAL_QUORUM",
            replication_strategy="NetworkTopologyStrategy",
            replication_factor=5,
            datacenter="dc1",
        )

        assert backend.contact_points == ["cassandra-1", "cassandra-2"]
        assert backend.port == 9043
        assert backend.keyspace == "custom_keyspace"
        assert backend.username == "testuser"
        assert backend.password == "testpass"
        assert backend.replication_strategy == "NetworkTopologyStrategy"
        assert backend.replication_factor == 5
        assert backend.datacenter == "dc1"


class TestCassandraStorageBackendConfig:
    """Test configuration and serialization methods."""

    def test_storage_to_config(self):
        """Test serializing backend to config dict."""
        from pyworkflow.storage.config import storage_to_config

        backend = CassandraStorageBackend(
            contact_points=["node1", "node2"],
            port=9043,
            keyspace="test_keyspace",
            username="user",
            password="pass",
        )

        config = storage_to_config(backend)

        assert config["type"] == "cassandra"
        assert config["contact_points"] == ["node1", "node2"]
        assert config["port"] == 9043
        assert config["keyspace"] == "test_keyspace"

    def test_config_to_storage(self):
        """Test deserializing config dict to backend."""
        from pyworkflow.storage.config import config_to_storage

        config = {
            "type": "cassandra",
            "contact_points": ["cassandra-host"],
            "port": 9042,
            "keyspace": "pyworkflow_test",
            "username": "testuser",
            "password": "testpass",
        }

        backend = config_to_storage(config)

        assert isinstance(backend, CassandraStorageBackend)
        assert backend.contact_points == ["cassandra-host"]
        assert backend.keyspace == "pyworkflow_test"


class TestCassandraStorageBackendConnection:
    """Test connection management."""

    @pytest.mark.asyncio
    async def test_connect_creates_keyspace_and_tables(self):
        """Test that connect creates keyspace and tables."""
        backend = CassandraStorageBackend(keyspace="test_keyspace")

        mock_cluster = MagicMock()
        mock_session = MagicMock()
        mock_cluster.connect.return_value = mock_session

        with patch("pyworkflow.storage.cassandra.Cluster", return_value=mock_cluster):
            await backend.connect()

            # Verify cluster was created
            mock_cluster.connect.assert_called_once()

            # Verify keyspace was created
            calls = mock_session.execute.call_args_list
            assert len(calls) > 0

            # First call should create keyspace
            first_call = str(calls[0])
            assert "CREATE KEYSPACE IF NOT EXISTS" in first_call

            assert backend._initialized is True

    @pytest.mark.asyncio
    async def test_disconnect_closes_session_and_cluster(
        self, mock_backend, mock_session, mock_cluster
    ):
        """Test that disconnect closes session and cluster."""
        await mock_backend.disconnect()

        mock_session.shutdown.assert_called_once()
        mock_cluster.shutdown.assert_called_once()
        assert mock_backend._initialized is False
        assert mock_backend._session is None
        assert mock_backend._cluster is None

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_healthy(self, mock_backend, mock_session):
        """Test health check returns True when query succeeds."""
        mock_session.execute.return_value = MagicMock()

        result = await mock_backend.health_check()

        assert result is True
        mock_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_no_session(self):
        """Test health check returns False when not connected."""
        backend = CassandraStorageBackend()
        backend._session = None

        result = await backend.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_error(self, mock_backend, mock_session):
        """Test health check returns False when query fails."""
        mock_session.execute.side_effect = Exception("Connection error")

        result = await mock_backend.health_check()

        assert result is False


class TestCassandraHelperMethods:
    """Test helper methods for bucketing and TIMEUUID generation."""

    def test_get_date_bucket(self, mock_backend):
        """Test date bucket generation."""
        dt = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
        bucket = mock_backend._get_date_bucket(dt)
        assert bucket == "2025-06-15"

    def test_get_hour_bucket(self, mock_backend):
        """Test hour bucket generation."""
        dt = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
        bucket = mock_backend._get_hour_bucket(dt)
        assert bucket == "2025-06-15-10"

    def test_get_date_buckets_returns_ordered_list(self, mock_backend):
        """Test that date buckets are ordered newest to oldest."""
        end_time = datetime(2025, 6, 15, tzinfo=UTC)
        start_time = datetime(2025, 6, 10, tzinfo=UTC)

        buckets = mock_backend._get_date_buckets(start_time, end_time, max_buckets=10)

        assert len(buckets) == 6  # 10-15 inclusive
        assert buckets[0] == "2025-06-15"  # Newest first
        assert buckets[-1] == "2025-06-10"  # Oldest last

    def test_generate_timeuuid_returns_valid_uuid(self, mock_backend):
        """Test TIMEUUID generation."""
        timeuuid = mock_backend._generate_timeuuid()
        assert isinstance(timeuuid, UUID)
        assert timeuuid.version == 1  # Time-based UUID


class TestWorkflowRunOperations:
    """Test workflow run CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_run(self, mock_backend, mock_session):
        """Test creating a workflow run."""
        now = datetime.now(UTC)
        run = WorkflowRun(
            run_id="test_run",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )

        await mock_backend.create_run(run)

        # Verify batch statement was executed
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_run_found(self, mock_backend, mock_session):
        """Test getting an existing workflow run."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.run_id = "test_run"
        mock_row.workflow_name = "test_workflow"
        mock_row.status = "pending"
        mock_row.created_at = now
        mock_row.updated_at = now
        mock_row.started_at = None
        mock_row.completed_at = None
        mock_row.input_args = "[]"
        mock_row.input_kwargs = "{}"
        mock_row.result = None
        mock_row.error = None
        mock_row.idempotency_key = None
        mock_row.max_duration = None
        mock_row.context = "{}"
        mock_row.recovery_attempts = 0
        mock_row.max_recovery_attempts = 3
        mock_row.recover_on_worker_loss = True
        mock_row.parent_run_id = None
        mock_row.nesting_depth = 0
        mock_row.continued_from_run_id = None
        mock_row.continued_to_run_id = None

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        result = await mock_backend.get_run("test_run")

        assert result is not None
        assert result.run_id == "test_run"
        assert result.workflow_name == "test_workflow"
        assert result.status == RunStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_run_not_found(self, mock_backend, mock_session):
        """Test getting a non-existent workflow run."""
        mock_result = MagicMock()
        mock_result.one.return_value = None
        mock_session.execute.return_value = mock_result

        result = await mock_backend.get_run("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_run_by_idempotency_key(self, mock_backend, mock_session):
        """Test getting run by idempotency key uses lookup table."""
        now = datetime.now(UTC)

        # First call returns the idempotency key lookup
        mock_lookup_row = MagicMock()
        mock_lookup_row.run_id = "test_run"
        mock_lookup_result = MagicMock()
        mock_lookup_result.one.return_value = mock_lookup_row

        # Second call returns the actual run
        mock_run_row = MagicMock()
        mock_run_row.run_id = "test_run"
        mock_run_row.workflow_name = "test"
        mock_run_row.status = "pending"
        mock_run_row.created_at = now
        mock_run_row.updated_at = now
        mock_run_row.started_at = None
        mock_run_row.completed_at = None
        mock_run_row.input_args = "[]"
        mock_run_row.input_kwargs = "{}"
        mock_run_row.result = None
        mock_run_row.error = None
        mock_run_row.idempotency_key = "my_key"
        mock_run_row.max_duration = None
        mock_run_row.context = "{}"
        mock_run_row.recovery_attempts = 0
        mock_run_row.max_recovery_attempts = 3
        mock_run_row.recover_on_worker_loss = True
        mock_run_row.parent_run_id = None
        mock_run_row.nesting_depth = 0
        mock_run_row.continued_from_run_id = None
        mock_run_row.continued_to_run_id = None

        mock_run_result = MagicMock()
        mock_run_result.one.return_value = mock_run_row

        mock_session.execute.side_effect = [mock_lookup_result, mock_run_result]

        result = await mock_backend.get_run_by_idempotency_key("my_key")

        assert result is not None
        assert result.run_id == "test_run"
        assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_update_run_status(self, mock_backend, mock_session):
        """Test updating run status."""
        now = datetime.now(UTC)

        # Mock get_run to return existing run
        mock_row = MagicMock()
        mock_row.run_id = "test_run"
        mock_row.workflow_name = "test_workflow"
        mock_row.status = "pending"
        mock_row.created_at = now
        mock_row.updated_at = now
        mock_row.started_at = None
        mock_row.completed_at = None
        mock_row.input_args = "[]"
        mock_row.input_kwargs = "{}"
        mock_row.result = None
        mock_row.error = None
        mock_row.idempotency_key = None
        mock_row.max_duration = None
        mock_row.context = "{}"
        mock_row.recovery_attempts = 0
        mock_row.max_recovery_attempts = 3
        mock_row.recover_on_worker_loss = True
        mock_row.parent_run_id = None
        mock_row.nesting_depth = 0
        mock_row.continued_from_run_id = None
        mock_row.continued_to_run_id = None

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        await mock_backend.update_run_status(
            run_id="test_run",
            status=RunStatus.RUNNING,
        )

        # Should have called get_run once, then batch execute
        assert mock_session.execute.call_count >= 1


class TestEventOperations:
    """Test event log operations."""

    @pytest.mark.asyncio
    async def test_record_event(self, mock_backend, mock_session):
        """Test recording an event with TIMEUUID."""
        now = datetime.now(UTC)
        event = Event(
            event_id="evt_1",
            run_id="test_run",
            type=EventType.WORKFLOW_STARTED,
            timestamp=now,
            data={},
        )

        await mock_backend.record_event(event)

        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_events(self, mock_backend, mock_session):
        """Test getting events for a run."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.event_id = "evt_1"
        mock_row.run_id = "test_run"
        mock_row.type = "workflow.started"
        mock_row.timestamp = now
        mock_row.data = "{}"

        mock_session.execute.return_value = [mock_row]

        events = await mock_backend.get_events("test_run")

        assert len(events) == 1
        assert events[0].event_id == "evt_1"
        assert events[0].type == EventType.WORKFLOW_STARTED
        assert events[0].sequence == 0

    @pytest.mark.asyncio
    async def test_get_events_with_type_filter(self, mock_backend, mock_session):
        """Test getting events filtered by type."""
        now = datetime.now(UTC)

        mock_row1 = MagicMock()
        mock_row1.event_id = "evt_1"
        mock_row1.run_id = "test_run"
        mock_row1.type = "workflow.started"
        mock_row1.timestamp = now
        mock_row1.data = "{}"

        mock_row2 = MagicMock()
        mock_row2.event_id = "evt_2"
        mock_row2.run_id = "test_run"
        mock_row2.type = "step.completed"
        mock_row2.timestamp = now
        mock_row2.data = "{}"

        mock_session.execute.return_value = [mock_row1, mock_row2]

        events = await mock_backend.get_events("test_run", event_types=["step.completed"])

        # Should filter to only step.completed
        assert len(events) == 1
        assert events[0].type == EventType.STEP_COMPLETED

    @pytest.mark.asyncio
    async def test_get_latest_event(self, mock_backend, mock_session):
        """Test getting latest event."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.event_id = "evt_5"
        mock_row.run_id = "test_run"
        mock_row.type = "step.completed"
        mock_row.timestamp = now
        mock_row.data = "{}"

        # First call for latest event, second for total count
        mock_session.execute.side_effect = [
            [mock_row],  # Latest event query
            [MagicMock() for _ in range(5)],  # Count query
        ]

        event = await mock_backend.get_latest_event("test_run")

        assert event is not None
        assert event.event_id == "evt_5"


class TestStepOperations:
    """Test step execution operations."""

    @pytest.mark.asyncio
    async def test_create_step(self, mock_backend, mock_session):
        """Test creating a step execution."""
        now = datetime.now(UTC)
        step = StepExecution(
            step_id="step_1",
            run_id="test_run",
            step_name="test_step",
            status=StepStatus.RUNNING,
            created_at=now,
            input_args="[]",
            input_kwargs="{}",
            attempt=1,
        )

        await mock_backend.create_step(step)

        # Should execute batch for both tables
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_step_found(self, mock_backend, mock_session):
        """Test getting an existing step via lookup table."""
        now = datetime.now(UTC)

        # First call returns lookup
        mock_lookup = MagicMock()
        mock_lookup.run_id = "test_run"
        mock_lookup_result = MagicMock()
        mock_lookup_result.one.return_value = mock_lookup

        # Second call returns full step
        mock_step = MagicMock()
        mock_step.step_id = "step_1"
        mock_step.run_id = "test_run"
        mock_step.step_name = "test_step"
        mock_step.status = "completed"
        mock_step.created_at = now
        mock_step.updated_at = now
        mock_step.started_at = now
        mock_step.completed_at = now
        mock_step.input_args = "[]"
        mock_step.input_kwargs = "{}"
        mock_step.result = None
        mock_step.error = None
        mock_step.attempt = 1
        mock_step.max_retries = 3
        mock_step.retry_after = None
        mock_step.retry_delay = None

        mock_step_result = MagicMock()
        mock_step_result.one.return_value = mock_step

        mock_session.execute.side_effect = [mock_lookup_result, mock_step_result]

        result = await mock_backend.get_step("step_1")

        assert result is not None
        assert result.step_id == "step_1"
        assert result.status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_get_step_not_found(self, mock_backend, mock_session):
        """Test getting a non-existent step."""
        mock_result = MagicMock()
        mock_result.one.return_value = None
        mock_session.execute.return_value = mock_result

        result = await mock_backend.get_step("nonexistent")

        assert result is None


class TestHookOperations:
    """Test hook/webhook operations."""

    @pytest.mark.asyncio
    async def test_create_hook(self, mock_backend, mock_session):
        """Test creating a hook."""
        now = datetime.now(UTC)
        hook = Hook(
            hook_id="hook_1",
            run_id="test_run",
            token="token_abc",
            status=HookStatus.PENDING,
            created_at=now,
        )

        await mock_backend.create_hook(hook)

        # Should execute batch for all 3 tables
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_hook_found(self, mock_backend, mock_session):
        """Test getting an existing hook via lookup table."""
        now = datetime.now(UTC)

        # First call returns lookup
        mock_lookup = MagicMock()
        mock_lookup.run_id = "test_run"
        mock_lookup_result = MagicMock()
        mock_lookup_result.one.return_value = mock_lookup

        # Second call returns full hook
        mock_hook = MagicMock()
        mock_hook.hook_id = "hook_1"
        mock_hook.run_id = "test_run"
        mock_hook.token = "token_abc"
        mock_hook.url = ""
        mock_hook.status = "pending"
        mock_hook.created_at = now
        mock_hook.received_at = None
        mock_hook.expires_at = None
        mock_hook.payload = None
        mock_hook.name = None
        mock_hook.payload_schema = None
        mock_hook.metadata = "{}"

        mock_hook_result = MagicMock()
        mock_hook_result.one.return_value = mock_hook

        mock_session.execute.side_effect = [mock_lookup_result, mock_hook_result]

        result = await mock_backend.get_hook("hook_1")

        assert result is not None
        assert result.hook_id == "hook_1"
        assert result.token == "token_abc"

    @pytest.mark.asyncio
    async def test_get_hook_by_token(self, mock_backend, mock_session):
        """Test getting hook by token."""
        now = datetime.now(UTC)

        # First call returns token lookup
        mock_lookup = MagicMock()
        mock_lookup.run_id = "test_run"
        mock_lookup.hook_id = "hook_1"
        mock_lookup_result = MagicMock()
        mock_lookup_result.one.return_value = mock_lookup

        # Second call returns full hook
        mock_hook = MagicMock()
        mock_hook.hook_id = "hook_1"
        mock_hook.run_id = "test_run"
        mock_hook.token = "token_abc"
        mock_hook.url = ""
        mock_hook.status = "pending"
        mock_hook.created_at = now
        mock_hook.received_at = None
        mock_hook.expires_at = None
        mock_hook.payload = None
        mock_hook.name = None
        mock_hook.payload_schema = None
        mock_hook.metadata = "{}"

        mock_hook_result = MagicMock()
        mock_hook_result.one.return_value = mock_hook

        mock_session.execute.side_effect = [mock_lookup_result, mock_hook_result]

        result = await mock_backend.get_hook_by_token("token_abc")

        assert result is not None
        assert result.token == "token_abc"


class TestCancellationOperations:
    """Test cancellation flag operations."""

    @pytest.mark.asyncio
    async def test_set_cancellation_flag(self, mock_backend, mock_session):
        """Test setting a cancellation flag."""
        await mock_backend.set_cancellation_flag("run_123")

        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_cancellation_flag_set(self, mock_backend, mock_session):
        """Test checking cancellation flag when it exists."""
        mock_result = MagicMock()
        mock_result.one.return_value = MagicMock(run_id="run_123")
        mock_session.execute.return_value = mock_result

        result = await mock_backend.check_cancellation_flag("run_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_cancellation_flag_not_set(self, mock_backend, mock_session):
        """Test checking cancellation flag when it doesn't exist."""
        mock_result = MagicMock()
        mock_result.one.return_value = None
        mock_session.execute.return_value = mock_result

        result = await mock_backend.check_cancellation_flag("run_123")

        assert result is False

    @pytest.mark.asyncio
    async def test_clear_cancellation_flag(self, mock_backend, mock_session):
        """Test clearing a cancellation flag."""
        await mock_backend.clear_cancellation_flag("run_123")

        mock_session.execute.assert_called_once()


class TestContinueAsNewOperations:
    """Test continue-as-new chain operations."""

    @pytest.mark.asyncio
    async def test_update_run_continuation(self, mock_backend, mock_session):
        """Test updating run continuation link."""
        await mock_backend.update_run_continuation("run_1", "run_2")

        mock_session.execute.assert_called_once()


class TestChildWorkflowOperations:
    """Test child workflow operations."""

    @pytest.mark.asyncio
    async def test_get_children(self, mock_backend, mock_session):
        """Test getting child workflows."""
        now = datetime.now(UTC)

        # Query result
        mock_child = MagicMock()
        mock_child.run_id = "child_1"
        mock_child.status = "completed"

        mock_session.execute.side_effect = [
            [mock_child],  # runs_by_parent query
            MagicMock(one=lambda: self._create_mock_run("child_1", now)),  # get_run
        ]

        # Mock get_run
        with patch.object(mock_backend, "get_run") as mock_get_run:
            mock_run = WorkflowRun(
                run_id="child_1",
                workflow_name="child_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
                updated_at=now,
                input_args="[]",
                input_kwargs="{}",
            )
            mock_get_run.return_value = mock_run

            result = await mock_backend.get_children("parent_123")

            assert len(result) == 1
            assert result[0].run_id == "child_1"

    def _create_mock_run(self, run_id: str, now: datetime):
        """Helper to create mock run row."""
        mock_row = MagicMock()
        mock_row.run_id = run_id
        mock_row.workflow_name = "test"
        mock_row.status = "completed"
        mock_row.created_at = now
        mock_row.updated_at = now
        return mock_row


class TestScheduleOperations:
    """Test schedule CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_schedule(self, mock_backend, mock_session):
        """Test creating a schedule."""
        now = datetime.now(UTC)
        schedule = Schedule(
            schedule_id="sched_1",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            status=ScheduleStatus.ACTIVE,
            created_at=now,
        )

        await mock_backend.create_schedule(schedule)

        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_schedule_found(self, mock_backend, mock_session):
        """Test getting an existing schedule."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.schedule_id = "sched_1"
        mock_row.workflow_name = "test_workflow"
        mock_row.spec = '{"cron": "0 9 * * *"}'
        mock_row.spec_type = "cron"
        mock_row.timezone = "UTC"
        mock_row.args = "[]"
        mock_row.kwargs = "{}"
        mock_row.status = "active"
        mock_row.overlap_policy = "skip"
        mock_row.created_at = now
        mock_row.updated_at = None
        mock_row.last_run_at = None
        mock_row.next_run_time = None
        mock_row.last_run_id = None
        mock_row.running_run_ids = "[]"
        mock_row.buffered_count = 0

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        result = await mock_backend.get_schedule("sched_1")

        assert result is not None
        assert result.schedule_id == "sched_1"
        assert result.status == ScheduleStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_get_schedule_not_found(self, mock_backend, mock_session):
        """Test getting a non-existent schedule."""
        mock_result = MagicMock()
        mock_result.one.return_value = None
        mock_session.execute.return_value = mock_result

        result = await mock_backend.get_schedule("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_due_schedules(self, mock_backend, mock_session):
        """Test getting due schedules with bucket walking."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.schedule_id = "sched_1"

        # Mock the hour bucket queries (25 hours of buckets)
        mock_session.execute.side_effect = [
            [mock_row],  # First bucket has a due schedule
            *[[] for _ in range(24)],  # Other buckets empty
        ]

        # Mock get_schedule
        with patch.object(mock_backend, "get_schedule") as mock_get:
            mock_schedule = Schedule(
                schedule_id="sched_1",
                workflow_name="test",
                spec=ScheduleSpec(cron="0 9 * * *"),
                status=ScheduleStatus.ACTIVE,
                created_at=now,
            )
            mock_get.return_value = mock_schedule

            result = await mock_backend.get_due_schedules(now)

            assert len(result) == 1
            assert result[0].schedule_id == "sched_1"


class TestRowConversion:
    """Test row-to-object conversion methods."""

    def test_row_to_workflow_run(self, mock_backend):
        """Test converting Cassandra row to WorkflowRun."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.run_id = "test_run"
        mock_row.workflow_name = "test_workflow"
        mock_row.status = "pending"
        mock_row.created_at = now
        mock_row.updated_at = now
        mock_row.started_at = None
        mock_row.completed_at = None
        mock_row.input_args = "[]"
        mock_row.input_kwargs = '{"key": "value"}'
        mock_row.result = None
        mock_row.error = None
        mock_row.idempotency_key = "my_key"
        mock_row.max_duration = "1h"
        mock_row.context = '{"step_data": "test"}'
        mock_row.recovery_attempts = 1
        mock_row.max_recovery_attempts = 5
        mock_row.recover_on_worker_loss = False
        mock_row.parent_run_id = "parent_run"
        mock_row.nesting_depth = 1
        mock_row.continued_from_run_id = None
        mock_row.continued_to_run_id = None

        run = mock_backend._row_to_workflow_run(mock_row)

        assert run.run_id == "test_run"
        assert run.workflow_name == "test_workflow"
        assert run.status == RunStatus.PENDING
        assert run.idempotency_key == "my_key"
        assert run.context == {"step_data": "test"}
        assert run.recover_on_worker_loss is False

    def test_row_to_event(self, mock_backend):
        """Test converting Cassandra row to Event."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.event_id = "evt_123"
        mock_row.run_id = "test_run"
        mock_row.type = "workflow.started"
        mock_row.timestamp = now
        mock_row.data = '{"key": "value"}'

        event = mock_backend._row_to_event(mock_row, sequence=5)

        assert event.event_id == "evt_123"
        assert event.run_id == "test_run"
        assert event.type == EventType.WORKFLOW_STARTED
        assert event.sequence == 5
        assert event.data == {"key": "value"}

    def test_row_to_step_execution(self, mock_backend):
        """Test converting Cassandra row to StepExecution."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.step_id = "step_123"
        mock_row.run_id = "test_run"
        mock_row.step_name = "process_data"
        mock_row.status = "completed"
        mock_row.created_at = now
        mock_row.updated_at = now
        mock_row.started_at = now
        mock_row.completed_at = now
        mock_row.input_args = "[]"
        mock_row.input_kwargs = "{}"
        mock_row.result = '{"output": "success"}'
        mock_row.error = None
        mock_row.attempt = 2
        mock_row.max_retries = 3
        mock_row.retry_after = None
        mock_row.retry_delay = "10s"

        step = mock_backend._row_to_step_execution(mock_row)

        assert step.step_id == "step_123"
        assert step.step_name == "process_data"
        assert step.status == StepStatus.COMPLETED
        assert step.attempt == 2

    def test_row_to_hook(self, mock_backend):
        """Test converting Cassandra row to Hook."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.hook_id = "hook_123"
        mock_row.run_id = "test_run"
        mock_row.token = "token_abc"
        mock_row.url = "https://example.com/webhook"
        mock_row.status = "received"
        mock_row.created_at = now
        mock_row.received_at = now
        mock_row.expires_at = None
        mock_row.payload = '{"data": "payload"}'
        mock_row.name = "my_hook"
        mock_row.payload_schema = None
        mock_row.metadata = '{"key": "value"}'

        hook = mock_backend._row_to_hook(mock_row)

        assert hook.hook_id == "hook_123"
        assert hook.token == "token_abc"
        assert hook.status == HookStatus.RECEIVED
        assert hook.url == "https://example.com/webhook"

    def test_row_to_schedule(self, mock_backend):
        """Test converting Cassandra row to Schedule."""
        now = datetime.now(UTC)

        mock_row = MagicMock()
        mock_row.schedule_id = "sched_123"
        mock_row.workflow_name = "scheduled_workflow"
        mock_row.spec = '{"cron": "0 9 * * *", "timezone": "UTC"}'
        mock_row.spec_type = "cron"
        mock_row.timezone = "UTC"
        mock_row.args = "[1, 2, 3]"
        mock_row.kwargs = '{"key": "value"}'
        mock_row.status = "active"
        mock_row.overlap_policy = "buffer_one"
        mock_row.created_at = now
        mock_row.updated_at = now
        mock_row.last_run_at = None
        mock_row.next_run_time = now
        mock_row.last_run_id = None
        mock_row.running_run_ids = '["run_1", "run_2"]'
        mock_row.buffered_count = 2

        schedule = mock_backend._row_to_schedule(mock_row)

        assert schedule.schedule_id == "sched_123"
        assert schedule.workflow_name == "scheduled_workflow"
        assert schedule.spec.cron == "0 9 * * *"
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.overlap_policy == OverlapPolicy.BUFFER_ONE
        assert schedule.running_run_ids == ["run_1", "run_2"]
