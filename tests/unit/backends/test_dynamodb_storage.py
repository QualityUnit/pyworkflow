"""
Unit tests for DynamoDB storage backend.

These tests verify the DynamoDBStorageBackend implementation.
For integration tests with a real DynamoDB database, see tests/integration/.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyworkflow.engine.events import Event, EventType
from pyworkflow.storage.schemas import (
    Hook,
    HookStatus,
    RunStatus,
    Schedule,
    ScheduleSpec,
    ScheduleStatus,
    StepExecution,
    StepStatus,
    WorkflowRun,
)

# Skip all tests if aiobotocore is not installed
pytest.importorskip("aiobotocore")

from pyworkflow.storage.dynamodb import DynamoDBStorageBackend


@pytest.fixture
def mock_backend():
    """Create a backend with mocked client for testing."""
    backend = DynamoDBStorageBackend()
    mock_client = AsyncMock()

    @asynccontextmanager
    async def mock_get_client():
        yield mock_client

    backend._get_client = mock_get_client
    return backend, mock_client


class TestDynamoDBStorageBackendInit:
    """Test DynamoDB backend initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        backend = DynamoDBStorageBackend()

        assert backend.table_name == "pyworkflow"
        assert backend.region == "us-east-1"
        assert backend.endpoint_url is None
        assert backend._initialized is False

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        backend = DynamoDBStorageBackend(
            table_name="custom_table",
            region="eu-west-1",
            endpoint_url="http://localhost:8000",
        )

        assert backend.table_name == "custom_table"
        assert backend.region == "eu-west-1"
        assert backend.endpoint_url == "http://localhost:8000"

    def test_init_with_local_endpoint(self):
        """Test initialization with DynamoDB Local endpoint."""
        backend = DynamoDBStorageBackend(
            endpoint_url="http://localhost:8000",
        )

        assert backend.endpoint_url == "http://localhost:8000"


class TestDynamoDBStorageBackendConfig:
    """Test configuration and serialization methods."""

    def test_storage_to_config(self):
        """Test serializing backend to config dict."""
        from pyworkflow.storage.config import storage_to_config

        backend = DynamoDBStorageBackend(
            table_name="my_table",
            region="us-west-2",
            endpoint_url="http://localhost:8000",
        )

        config = storage_to_config(backend)

        assert config["type"] == "dynamodb"
        assert config["table_name"] == "my_table"
        assert config["region"] == "us-west-2"
        assert config["endpoint_url"] == "http://localhost:8000"

    def test_config_to_storage(self):
        """Test deserializing config dict to backend."""
        from pyworkflow.storage.config import config_to_storage

        config = {
            "type": "dynamodb",
            "table_name": "test_table",
            "region": "ap-northeast-1",
            "endpoint_url": "http://localhost:8000",
        }

        backend = config_to_storage(config)

        assert isinstance(backend, DynamoDBStorageBackend)
        assert backend.table_name == "test_table"
        assert backend.region == "ap-northeast-1"
        assert backend.endpoint_url == "http://localhost:8000"


class TestDynamoDBStorageBackendConnection:
    """Test connection management."""

    @pytest.mark.asyncio
    async def test_connect_creates_table_if_not_exists(self):
        """Test that connect creates table if it doesn't exist."""
        backend = DynamoDBStorageBackend(table_name="test_table")

        mock_client = AsyncMock()
        from botocore.exceptions import ClientError

        mock_client.describe_table = AsyncMock(
            side_effect=ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}},
                "DescribeTable",
            )
        )
        mock_client.create_table = AsyncMock()

        mock_waiter = AsyncMock()
        mock_waiter.wait = AsyncMock()
        mock_client.get_waiter = MagicMock(return_value=mock_waiter)

        with patch.object(backend, "_get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_client)
            mock_context.__aexit__ = AsyncMock()
            mock_get_client.return_value = mock_context

            await backend.connect()

            mock_client.create_table.assert_called_once()
            call_kwargs = mock_client.create_table.call_args.kwargs

            assert call_kwargs["TableName"] == "test_table"
            assert call_kwargs["BillingMode"] == "PAY_PER_REQUEST"

            # Verify GSIs were created
            gsi_names = [gsi["IndexName"] for gsi in call_kwargs["GlobalSecondaryIndexes"]]
            assert "GSI1" in gsi_names
            assert "GSI2" in gsi_names
            assert "GSI3" in gsi_names
            assert "GSI4" in gsi_names
            assert "GSI5" in gsi_names

    @pytest.mark.asyncio
    async def test_connect_skips_create_if_table_exists(self):
        """Test that connect doesn't create table if it exists."""
        backend = DynamoDBStorageBackend()

        mock_client = AsyncMock()
        mock_client.describe_table = AsyncMock(return_value={"Table": {}})
        mock_client.create_table = AsyncMock()

        with patch.object(backend, "_get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_client)
            mock_context.__aexit__ = AsyncMock()
            mock_get_client.return_value = mock_context

            await backend.connect()

            mock_client.create_table.assert_not_called()
            assert backend._initialized is True

    @pytest.mark.asyncio
    async def test_disconnect_sets_initialized_to_false(self):
        """Test that disconnect sets _initialized to False."""
        backend = DynamoDBStorageBackend()
        backend._initialized = True

        await backend.disconnect()

        assert backend._initialized is False

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_healthy(self, mock_backend):
        """Test health check returns True when list_runs succeeds."""
        backend, mock_client = mock_backend

        # Mock list_runs to return empty result
        mock_client.query = AsyncMock(return_value={"Items": []})

        with patch.object(backend, "list_runs", return_value=([], None)):
            result = await backend.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_error(self):
        """Test health check returns False when list_runs fails."""
        backend = DynamoDBStorageBackend()

        with patch.object(backend, "list_runs", side_effect=Exception("Connection error")):
            result = await backend.health_check()

        assert result is False


class TestDynamoDBSerialization:
    """Test DynamoDB value serialization/deserialization."""

    @pytest.fixture
    def backend(self):
        """Create a DynamoDB backend instance."""
        return DynamoDBStorageBackend()

    def test_serialize_string(self, backend):
        """Test serializing string values."""
        result = backend._serialize_value("test")
        assert result == {"S": "test"}

    def test_serialize_int(self, backend):
        """Test serializing integer values."""
        result = backend._serialize_value(42)
        assert result == {"N": "42"}

    def test_serialize_float(self, backend):
        """Test serializing float values."""
        result = backend._serialize_value(3.14)
        assert result == {"N": "3.14"}

    def test_serialize_bool(self, backend):
        """Test serializing boolean values."""
        assert backend._serialize_value(True) == {"BOOL": True}
        assert backend._serialize_value(False) == {"BOOL": False}

    def test_serialize_none(self, backend):
        """Test serializing None values."""
        result = backend._serialize_value(None)
        assert result == {"NULL": True}

    def test_serialize_list(self, backend):
        """Test serializing list values."""
        result = backend._serialize_value(["a", 1, True])
        assert result == {"L": [{"S": "a"}, {"N": "1"}, {"BOOL": True}]}

    def test_serialize_dict(self, backend):
        """Test serializing dict values."""
        result = backend._serialize_value({"key": "value", "num": 42})
        assert result == {"M": {"key": {"S": "value"}, "num": {"N": "42"}}}

    def test_deserialize_string(self, backend):
        """Test deserializing string values."""
        result = backend._deserialize_value({"S": "test"})
        assert result == "test"

    def test_deserialize_number_int(self, backend):
        """Test deserializing integer number values."""
        result = backend._deserialize_value({"N": "42"})
        assert result == 42

    def test_deserialize_number_float(self, backend):
        """Test deserializing float number values."""
        result = backend._deserialize_value({"N": "3.14"})
        assert result == 3.14

    def test_deserialize_bool(self, backend):
        """Test deserializing boolean values."""
        assert backend._deserialize_value({"BOOL": True}) is True
        assert backend._deserialize_value({"BOOL": False}) is False

    def test_deserialize_null(self, backend):
        """Test deserializing null values."""
        result = backend._deserialize_value({"NULL": True})
        assert result is None

    def test_deserialize_list(self, backend):
        """Test deserializing list values."""
        result = backend._deserialize_value({"L": [{"S": "a"}, {"N": "1"}, {"BOOL": True}]})
        assert result == ["a", 1, True]

    def test_deserialize_dict(self, backend):
        """Test deserializing dict values."""
        result = backend._deserialize_value({"M": {"key": {"S": "value"}, "num": {"N": "42"}}})
        assert result == {"key": "value", "num": 42}


class TestDynamoDBItemConversion:
    """Test item-to-object conversion methods."""

    @pytest.fixture
    def backend(self):
        """Create a DynamoDB backend instance."""
        return DynamoDBStorageBackend()

    def test_item_to_workflow_run(self, backend):
        """Test converting DynamoDB item to WorkflowRun."""
        now = datetime.now(UTC)
        item = {
            "run_id": "test_run",
            "workflow_name": "test_workflow",
            "status": "pending",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "input_args": "[]",
            "input_kwargs": "{}",
            "metadata": "{}",
            "recovery_attempts": 0,
            "max_recovery_attempts": 3,
            "recover_on_worker_loss": True,
            "nesting_depth": 0,
        }

        run = backend._item_to_workflow_run(item)

        assert run.run_id == "test_run"
        assert run.workflow_name == "test_workflow"
        assert run.status == RunStatus.PENDING
        assert run.recovery_attempts == 0

    def test_item_to_event(self, backend):
        """Test converting DynamoDB item to Event."""
        now = datetime.now(UTC)
        item = {
            "event_id": "evt_123",
            "run_id": "test_run",
            "sequence": 0,
            "type": "workflow.started",
            "timestamp": now.isoformat(),
            "data": '{"key": "value"}',
        }

        event = backend._item_to_event(item)

        assert event.event_id == "evt_123"
        assert event.run_id == "test_run"
        assert event.type == EventType.WORKFLOW_STARTED
        assert event.data == {"key": "value"}

    def test_item_to_step_execution(self, backend):
        """Test converting DynamoDB item to StepExecution."""
        now = datetime.now(UTC)
        item = {
            "step_id": "step_123",
            "run_id": "test_run",
            "step_name": "test_step",
            "status": "completed",
            "created_at": now.isoformat(),
            "input_args": "[]",
            "input_kwargs": "{}",
            "retry_count": 0,
        }

        step = backend._item_to_step_execution(item)

        assert step.step_id == "step_123"
        assert step.run_id == "test_run"
        assert step.step_name == "test_step"
        assert step.status == StepStatus.COMPLETED
        assert step.attempt == 1  # retry_count + 1

    def test_item_to_hook(self, backend):
        """Test converting DynamoDB item to Hook."""
        now = datetime.now(UTC)
        item = {
            "hook_id": "hook_123",
            "run_id": "test_run",
            "token": "token_abc",
            "created_at": now.isoformat(),
            "status": "pending",
            "metadata": "{}",
        }

        hook = backend._item_to_hook(item)

        assert hook.hook_id == "hook_123"
        assert hook.run_id == "test_run"
        assert hook.token == "token_abc"
        assert hook.status == HookStatus.PENDING

    def test_item_to_schedule(self, backend):
        """Test converting DynamoDB item to Schedule."""
        now = datetime.now(UTC)
        item = {
            "schedule_id": "sched_123",
            "workflow_name": "test_workflow",
            "spec": "0 9 * * *",
            "spec_type": "cron",
            "timezone": "UTC",
            "status": "active",
            "input_args": "[]",
            "input_kwargs": "{}",
            "overlap_policy": "skip",
            "created_at": now.isoformat(),
            "running_run_ids": "[]",
        }

        schedule = backend._item_to_schedule(item)

        assert schedule.schedule_id == "sched_123"
        assert schedule.workflow_name == "test_workflow"
        assert schedule.spec.cron == "0 9 * * *"
        assert schedule.status == ScheduleStatus.ACTIVE


class TestDynamoDBKeyPatterns:
    """Test DynamoDB key pattern generation."""

    @pytest.fixture
    def backend(self):
        """Create a DynamoDB backend instance."""
        return DynamoDBStorageBackend()

    @pytest.mark.asyncio
    async def test_workflow_run_key_pattern(self, backend):
        """Test that workflow run uses correct key pattern."""
        now = datetime.now(UTC)
        run = WorkflowRun(
            run_id="test_run_123",
            workflow_name="test_workflow",
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
            input_args="[]",
            input_kwargs="{}",
        )

        mock_client = AsyncMock()
        mock_client.put_item = AsyncMock()

        with patch.object(backend, "_get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_client)
            mock_context.__aexit__ = AsyncMock()
            mock_get_client.return_value = mock_context

            await backend.create_run(run)

            call_args = mock_client.put_item.call_args
            item = call_args.kwargs["Item"]

            assert item["PK"]["S"] == "RUN#test_run_123"
            assert item["SK"]["S"] == "#METADATA"
            assert item["GSI1PK"]["S"] == "RUNS"

    @pytest.mark.asyncio
    async def test_event_key_pattern(self, backend):
        """Test that events use correct key pattern with sequence."""
        now = datetime.now(UTC)
        event = Event(
            event_id="evt_123",
            run_id="test_run_123",
            type=EventType.WORKFLOW_STARTED,
            timestamp=now,
            data={},
        )

        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={"Attributes": {"seq": {"N": "1"}}})
        mock_client.put_item = AsyncMock()

        with patch.object(backend, "_get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_client)
            mock_context.__aexit__ = AsyncMock()
            mock_get_client.return_value = mock_context

            await backend.record_event(event)

            put_call = mock_client.put_item.call_args
            item = put_call.kwargs["Item"]

            assert item["PK"]["S"] == "RUN#test_run_123"
            assert item["SK"]["S"].startswith("EVENT#")


class TestWorkflowRunOperations:
    """Test workflow run CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_run(self, mock_backend):
        """Test creating a workflow run."""
        backend, mock_client = mock_backend
        mock_client.put_item = AsyncMock()

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

        await backend.create_run(run)

        mock_client.put_item.assert_called_once()
        call_kwargs = mock_client.put_item.call_args.kwargs
        assert call_kwargs["TableName"] == "pyworkflow"
        assert "PK" in call_kwargs["Item"]

    @pytest.mark.asyncio
    async def test_get_run_found(self, mock_backend):
        """Test getting an existing workflow run."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.get_item = AsyncMock(
            return_value={
                "Item": {
                    "run_id": {"S": "test_run"},
                    "workflow_name": {"S": "test_workflow"},
                    "status": {"S": "pending"},
                    "created_at": {"S": now.isoformat()},
                    "updated_at": {"S": now.isoformat()},
                    "input_args": {"S": "[]"},
                    "input_kwargs": {"S": "{}"},
                    "metadata": {"S": "{}"},
                    "recovery_attempts": {"N": "0"},
                    "max_recovery_attempts": {"N": "3"},
                    "recover_on_worker_loss": {"BOOL": True},
                    "nesting_depth": {"N": "0"},
                }
            }
        )

        result = await backend.get_run("test_run")

        assert result is not None
        assert result.run_id == "test_run"
        assert result.workflow_name == "test_workflow"

    @pytest.mark.asyncio
    async def test_get_run_not_found(self, mock_backend):
        """Test getting a non-existent workflow run."""
        backend, mock_client = mock_backend
        mock_client.get_item = AsyncMock(return_value={})

        result = await backend.get_run("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_run_by_idempotency_key(self, mock_backend):
        """Test getting run by idempotency key uses GSI3."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "run_id": {"S": "test_run"},
                        "workflow_name": {"S": "test_workflow"},
                        "status": {"S": "pending"},
                        "created_at": {"S": now.isoformat()},
                        "updated_at": {"S": now.isoformat()},
                        "input_args": {"S": "[]"},
                        "input_kwargs": {"S": "{}"},
                        "metadata": {"S": "{}"},
                        "recovery_attempts": {"N": "0"},
                        "max_recovery_attempts": {"N": "3"},
                        "recover_on_worker_loss": {"BOOL": True},
                        "nesting_depth": {"N": "0"},
                    }
                ]
            }
        )

        result = await backend.get_run_by_idempotency_key("my_key")

        call_args = mock_client.query.call_args
        assert call_args.kwargs["IndexName"] == "GSI3"
        assert result is not None
        assert result.run_id == "test_run"

    @pytest.mark.asyncio
    async def test_update_run_status(self, mock_backend):
        """Test updating run status."""
        backend, mock_client = mock_backend
        mock_client.update_item = AsyncMock()

        await backend.update_run_status(
            run_id="test_run",
            status=RunStatus.RUNNING,
        )

        mock_client.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_runs(self, mock_backend):
        """Test listing workflow runs."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "run_id": {"S": "run_1"},
                        "workflow_name": {"S": "test"},
                        "status": {"S": "pending"},
                        "created_at": {"S": now.isoformat()},
                        "updated_at": {"S": now.isoformat()},
                        "input_args": {"S": "[]"},
                        "input_kwargs": {"S": "{}"},
                        "metadata": {"S": "{}"},
                        "recovery_attempts": {"N": "0"},
                        "max_recovery_attempts": {"N": "3"},
                        "recover_on_worker_loss": {"BOOL": True},
                        "nesting_depth": {"N": "0"},
                    }
                ]
            }
        )

        runs, cursor = await backend.list_runs()

        assert len(runs) == 1
        assert runs[0].run_id == "run_1"


class TestEventOperations:
    """Test event log operations."""

    @pytest.mark.asyncio
    async def test_record_event(self, mock_backend):
        """Test recording an event."""
        backend, mock_client = mock_backend
        mock_client.update_item = AsyncMock(return_value={"Attributes": {"seq": {"N": "1"}}})
        mock_client.put_item = AsyncMock()

        now = datetime.now(UTC)
        event = Event(
            event_id="evt_1",
            run_id="test_run",
            type=EventType.WORKFLOW_STARTED,
            timestamp=now,
            data={},
        )

        await backend.record_event(event)

        mock_client.put_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_events(self, mock_backend):
        """Test getting events for a run."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "event_id": {"S": "evt_1"},
                        "run_id": {"S": "test_run"},
                        "sequence": {"N": "0"},
                        "type": {"S": "workflow.started"},
                        "timestamp": {"S": now.isoformat()},
                        "data": {"S": "{}"},
                    }
                ]
            }
        )

        events = await backend.get_events("test_run")

        assert len(events) == 1
        assert events[0].event_id == "evt_1"

    @pytest.mark.asyncio
    async def test_get_latest_event(self, mock_backend):
        """Test getting latest event for a run."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "event_id": {"S": "evt_5"},
                        "run_id": {"S": "test_run"},
                        "sequence": {"N": "5"},
                        "type": {"S": "step.completed"},
                        "timestamp": {"S": now.isoformat()},
                        "data": {"S": "{}"},
                    }
                ]
            }
        )

        event = await backend.get_latest_event("test_run")

        assert event is not None
        assert event.event_id == "evt_5"


class TestStepOperations:
    """Test step execution operations."""

    @pytest.mark.asyncio
    async def test_create_step(self, mock_backend):
        """Test creating a step execution."""
        backend, mock_client = mock_backend
        mock_client.put_item = AsyncMock()

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

        await backend.create_step(step)

        mock_client.put_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_step_found(self, mock_backend):
        """Test getting an existing step."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.scan = AsyncMock(
            return_value={
                "Items": [
                    {
                        "step_id": {"S": "step_1"},
                        "run_id": {"S": "test_run"},
                        "step_name": {"S": "test_step"},
                        "status": {"S": "completed"},
                        "created_at": {"S": now.isoformat()},
                        "input_args": {"S": "[]"},
                        "input_kwargs": {"S": "{}"},
                        "retry_count": {"N": "0"},
                    }
                ]
            }
        )

        result = await backend.get_step("step_1")

        assert result is not None
        assert result.step_id == "step_1"

    @pytest.mark.asyncio
    async def test_get_step_not_found(self, mock_backend):
        """Test getting a non-existent step."""
        backend, mock_client = mock_backend
        mock_client.scan = AsyncMock(return_value={"Items": []})

        result = await backend.get_step("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_update_step_status(self, mock_backend):
        """Test updating step status."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        # Mock get_step to return a step
        mock_client.scan = AsyncMock(
            return_value={
                "Items": [
                    {
                        "step_id": {"S": "step_1"},
                        "run_id": {"S": "test_run"},
                        "step_name": {"S": "test_step"},
                        "status": {"S": "running"},
                        "created_at": {"S": now.isoformat()},
                        "input_args": {"S": "[]"},
                        "input_kwargs": {"S": "{}"},
                        "retry_count": {"N": "0"},
                    }
                ]
            }
        )
        mock_client.update_item = AsyncMock()

        await backend.update_step_status(
            step_id="step_1",
            status="completed",
            result='{"output": "success"}',
        )

        mock_client.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_steps(self, mock_backend):
        """Test listing steps for a run."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "step_id": {"S": "step_1"},
                        "run_id": {"S": "test_run"},
                        "step_name": {"S": "step_1"},
                        "status": {"S": "completed"},
                        "created_at": {"S": now.isoformat()},
                        "input_args": {"S": "[]"},
                        "input_kwargs": {"S": "{}"},
                        "retry_count": {"N": "0"},
                    }
                ]
            }
        )

        steps = await backend.list_steps("test_run")

        assert len(steps) == 1


class TestHookOperations:
    """Test hook/webhook operations."""

    @pytest.mark.asyncio
    async def test_create_hook(self, mock_backend):
        """Test creating a hook."""
        backend, mock_client = mock_backend
        mock_client.put_item = AsyncMock()

        now = datetime.now(UTC)
        hook = Hook(
            hook_id="hook_1",
            run_id="test_run",
            token="token_abc",
            status=HookStatus.PENDING,
            created_at=now,
        )

        await backend.create_hook(hook)

        # Should be called twice (hook record + token lookup)
        assert mock_client.put_item.call_count == 2

    @pytest.mark.asyncio
    async def test_get_hook_found(self, mock_backend):
        """Test getting an existing hook."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.get_item = AsyncMock(
            return_value={
                "Item": {
                    "hook_id": {"S": "hook_1"},
                    "run_id": {"S": "test_run"},
                    "token": {"S": "token_abc"},
                    "status": {"S": "pending"},
                    "created_at": {"S": now.isoformat()},
                    "metadata": {"S": "{}"},
                }
            }
        )

        result = await backend.get_hook("hook_1")

        assert result is not None
        assert result.hook_id == "hook_1"

    @pytest.mark.asyncio
    async def test_get_hook_not_found(self, mock_backend):
        """Test getting a non-existent hook."""
        backend, mock_client = mock_backend
        mock_client.get_item = AsyncMock(return_value={})

        result = await backend.get_hook("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_hook_by_token(self, mock_backend):
        """Test getting hook by token."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        # First query returns the token lookup item with hook_id
        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "PK": {"S": "TOKEN#token_abc"},
                        "SK": {"S": "TOKEN#token_abc"},
                        "hook_id": {"S": "hook_1"},
                    }
                ]
            }
        )

        # Then get_item fetches the actual hook
        mock_client.get_item = AsyncMock(
            return_value={
                "Item": {
                    "hook_id": {"S": "hook_1"},
                    "run_id": {"S": "test_run"},
                    "token": {"S": "token_abc"},
                    "status": {"S": "pending"},
                    "created_at": {"S": now.isoformat()},
                    "metadata": {"S": "{}"},
                }
            }
        )

        result = await backend.get_hook_by_token("token_abc")

        assert result is not None
        assert result.token == "token_abc"
        mock_client.query.assert_called_once()
        mock_client.get_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_hook_status(self, mock_backend):
        """Test updating hook status."""
        backend, mock_client = mock_backend
        mock_client.update_item = AsyncMock()

        await backend.update_hook_status(
            hook_id="hook_1",
            status=HookStatus.RECEIVED,
            payload='{"data": "payload"}',
        )

        mock_client.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_hooks(self, mock_backend):
        """Test listing hooks for a run."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "hook_id": {"S": "hook_1"},
                        "run_id": {"S": "test_run"},
                        "token": {"S": "token_abc"},
                        "status": {"S": "pending"},
                        "created_at": {"S": now.isoformat()},
                        "metadata": {"S": "{}"},
                    }
                ]
            }
        )

        hooks = await backend.list_hooks(run_id="test_run")

        assert len(hooks) == 1


class TestCancellationOperations:
    """Test cancellation flag operations."""

    @pytest.mark.asyncio
    async def test_set_cancellation_flag(self, mock_backend):
        """Test setting a cancellation flag."""
        backend, mock_client = mock_backend
        mock_client.put_item = AsyncMock()

        await backend.set_cancellation_flag("run_123")

        call_args = mock_client.put_item.call_args
        item = call_args.kwargs["Item"]
        assert item["PK"]["S"] == "CANCEL#run_123"
        assert item["SK"]["S"] == "#FLAG"

    @pytest.mark.asyncio
    async def test_check_cancellation_flag_set(self, mock_backend):
        """Test checking cancellation flag when it exists."""
        backend, mock_client = mock_backend
        mock_client.get_item = AsyncMock(return_value={"Item": {"PK": {"S": "CANCEL#run_123"}}})

        result = await backend.check_cancellation_flag("run_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_cancellation_flag_not_set(self, mock_backend):
        """Test checking cancellation flag when it doesn't exist."""
        backend, mock_client = mock_backend
        mock_client.get_item = AsyncMock(return_value={})

        result = await backend.check_cancellation_flag("run_123")

        assert result is False

    @pytest.mark.asyncio
    async def test_clear_cancellation_flag(self, mock_backend):
        """Test clearing a cancellation flag."""
        backend, mock_client = mock_backend
        mock_client.delete_item = AsyncMock()

        await backend.clear_cancellation_flag("run_123")

        call_args = mock_client.delete_item.call_args
        key = call_args.kwargs["Key"]
        assert key["PK"]["S"] == "CANCEL#run_123"
        assert key["SK"]["S"] == "#FLAG"


class TestContinueAsNewOperations:
    """Test continue-as-new chain operations."""

    @pytest.mark.asyncio
    async def test_update_run_continuation(self, mock_backend):
        """Test updating run continuation link."""
        backend, mock_client = mock_backend
        mock_client.update_item = AsyncMock()

        await backend.update_run_continuation("run_1", "run_2")

        mock_client.update_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_workflow_chain(self, mock_backend):
        """Test getting workflow chain."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        # Chain: run_1 -> run_2
        # run_1: first in chain (no continued_from_run_id), has continued_to_run_id
        # run_2: second in chain, has continued_from_run_id, no continued_to_run_id
        run_1_item = {
            "Item": {
                "run_id": {"S": "run_1"},
                "workflow_name": {"S": "test"},
                "status": {"S": "completed"},
                "created_at": {"S": now.isoformat()},
                "updated_at": {"S": now.isoformat()},
                "input_args": {"S": "[]"},
                "input_kwargs": {"S": "{}"},
                "metadata": {"S": "{}"},
                "recovery_attempts": {"N": "0"},
                "max_recovery_attempts": {"N": "3"},
                "recover_on_worker_loss": {"BOOL": True},
                "nesting_depth": {"N": "0"},
                "continued_to_run_id": {"S": "run_2"},
            }
        }
        run_2_item = {
            "Item": {
                "run_id": {"S": "run_2"},
                "workflow_name": {"S": "test"},
                "status": {"S": "completed"},
                "created_at": {"S": now.isoformat()},
                "updated_at": {"S": now.isoformat()},
                "input_args": {"S": "[]"},
                "input_kwargs": {"S": "{}"},
                "metadata": {"S": "{}"},
                "recovery_attempts": {"N": "0"},
                "max_recovery_attempts": {"N": "3"},
                "recover_on_worker_loss": {"BOOL": True},
                "nesting_depth": {"N": "0"},
                "continued_from_run_id": {"S": "run_1"},
            }
        }

        # Mock get_item to return different items based on which run is requested
        async def mock_get_item(**kwargs):
            key = kwargs.get("Key", {})
            pk = key.get("PK", {}).get("S", "")
            if "run_1" in pk:
                return run_1_item
            elif "run_2" in pk:
                return run_2_item
            return {}

        mock_client.get_item = AsyncMock(side_effect=mock_get_item)

        result = await backend.get_workflow_chain("run_2")

        assert len(result) == 2
        assert result[0].run_id == "run_1"
        assert result[1].run_id == "run_2"


class TestChildWorkflowOperations:
    """Test child workflow operations."""

    @pytest.mark.asyncio
    async def test_get_children(self, mock_backend):
        """Test getting child workflows uses GSI4."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "run_id": {"S": "child_1"},
                        "workflow_name": {"S": "child_workflow"},
                        "status": {"S": "completed"},
                        "created_at": {"S": now.isoformat()},
                        "updated_at": {"S": now.isoformat()},
                        "input_args": {"S": "[]"},
                        "input_kwargs": {"S": "{}"},
                        "metadata": {"S": "{}"},
                        "recovery_attempts": {"N": "0"},
                        "max_recovery_attempts": {"N": "3"},
                        "recover_on_worker_loss": {"BOOL": True},
                        "nesting_depth": {"N": "1"},
                        "parent_run_id": {"S": "parent_123"},
                    }
                ]
            }
        )

        result = await backend.get_children("parent_123")

        call_args = mock_client.query.call_args
        assert call_args.kwargs["IndexName"] == "GSI4"
        assert len(result) == 1
        assert result[0].run_id == "child_1"

    @pytest.mark.asyncio
    async def test_get_parent_found(self, mock_backend):
        """Test getting parent workflow."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        # First call returns child run
        child_response = {
            "Item": {
                "run_id": {"S": "child_1"},
                "workflow_name": {"S": "child"},
                "status": {"S": "running"},
                "created_at": {"S": now.isoformat()},
                "updated_at": {"S": now.isoformat()},
                "input_args": {"S": "[]"},
                "input_kwargs": {"S": "{}"},
                "metadata": {"S": "{}"},
                "recovery_attempts": {"N": "0"},
                "max_recovery_attempts": {"N": "3"},
                "recover_on_worker_loss": {"BOOL": True},
                "nesting_depth": {"N": "1"},
                "parent_run_id": {"S": "parent_1"},
            }
        }

        # Second call returns parent run
        parent_response = {
            "Item": {
                "run_id": {"S": "parent_1"},
                "workflow_name": {"S": "parent"},
                "status": {"S": "running"},
                "created_at": {"S": now.isoformat()},
                "updated_at": {"S": now.isoformat()},
                "input_args": {"S": "[]"},
                "input_kwargs": {"S": "{}"},
                "metadata": {"S": "{}"},
                "recovery_attempts": {"N": "0"},
                "max_recovery_attempts": {"N": "3"},
                "recover_on_worker_loss": {"BOOL": True},
                "nesting_depth": {"N": "0"},
            }
        }

        mock_client.get_item = AsyncMock(side_effect=[child_response, parent_response])

        result = await backend.get_parent("child_1")

        assert result is not None
        assert result.run_id == "parent_1"

    @pytest.mark.asyncio
    async def test_get_parent_not_found(self, mock_backend):
        """Test getting parent when no parent exists."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.get_item = AsyncMock(
            return_value={
                "Item": {
                    "run_id": {"S": "root_run"},
                    "workflow_name": {"S": "test"},
                    "status": {"S": "running"},
                    "created_at": {"S": now.isoformat()},
                    "updated_at": {"S": now.isoformat()},
                    "input_args": {"S": "[]"},
                    "input_kwargs": {"S": "{}"},
                    "metadata": {"S": "{}"},
                    "recovery_attempts": {"N": "0"},
                    "max_recovery_attempts": {"N": "3"},
                    "recover_on_worker_loss": {"BOOL": True},
                    "nesting_depth": {"N": "0"},
                }
            }
        )

        result = await backend.get_parent("root_run")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_nesting_depth(self, mock_backend):
        """Test getting nesting depth."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.get_item = AsyncMock(
            return_value={
                "Item": {
                    "run_id": {"S": "child_run"},
                    "workflow_name": {"S": "test"},
                    "status": {"S": "running"},
                    "created_at": {"S": now.isoformat()},
                    "updated_at": {"S": now.isoformat()},
                    "input_args": {"S": "[]"},
                    "input_kwargs": {"S": "{}"},
                    "metadata": {"S": "{}"},
                    "recovery_attempts": {"N": "0"},
                    "max_recovery_attempts": {"N": "3"},
                    "recover_on_worker_loss": {"BOOL": True},
                    "nesting_depth": {"N": "2"},
                }
            }
        )

        result = await backend.get_nesting_depth("child_run")

        assert result == 2


class TestScheduleOperations:
    """Test schedule CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_schedule(self, mock_backend):
        """Test creating a schedule."""
        backend, mock_client = mock_backend
        mock_client.put_item = AsyncMock()

        now = datetime.now(UTC)
        schedule = Schedule(
            schedule_id="sched_1",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 9 * * *"),
            status=ScheduleStatus.ACTIVE,
            created_at=now,
        )

        await backend.create_schedule(schedule)

        mock_client.put_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_schedule_found(self, mock_backend):
        """Test getting an existing schedule."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.get_item = AsyncMock(
            return_value={
                "Item": {
                    "schedule_id": {"S": "sched_1"},
                    "workflow_name": {"S": "test_workflow"},
                    "spec": {"S": "0 9 * * *"},
                    "spec_type": {"S": "cron"},
                    "timezone": {"S": "UTC"},
                    "status": {"S": "active"},
                    "input_args": {"S": "[]"},
                    "input_kwargs": {"S": "{}"},
                    "overlap_policy": {"S": "skip"},
                    "created_at": {"S": now.isoformat()},
                    "running_run_ids": {"S": "[]"},
                }
            }
        )

        result = await backend.get_schedule("sched_1")

        assert result is not None
        assert result.schedule_id == "sched_1"

    @pytest.mark.asyncio
    async def test_get_schedule_not_found(self, mock_backend):
        """Test getting a non-existent schedule."""
        backend, mock_client = mock_backend
        mock_client.get_item = AsyncMock(return_value={})

        result = await backend.get_schedule("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_update_schedule(self, mock_backend):
        """Test updating a schedule."""
        backend, mock_client = mock_backend
        mock_client.put_item = AsyncMock()

        now = datetime.now(UTC)
        schedule = Schedule(
            schedule_id="sched_1",
            workflow_name="test_workflow",
            spec=ScheduleSpec(cron="0 10 * * *"),
            status=ScheduleStatus.PAUSED,
            created_at=now,
        )

        await backend.update_schedule(schedule)

        mock_client.put_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_schedule(self, mock_backend):
        """Test deleting a schedule."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.get_item = AsyncMock(
            return_value={
                "Item": {
                    "schedule_id": {"S": "sched_1"},
                    "workflow_name": {"S": "test"},
                    "spec": {"S": "0 9 * * *"},
                    "spec_type": {"S": "cron"},
                    "timezone": {"S": "UTC"},
                    "status": {"S": "active"},
                    "input_args": {"S": "[]"},
                    "input_kwargs": {"S": "{}"},
                    "overlap_policy": {"S": "skip"},
                    "created_at": {"S": now.isoformat()},
                    "running_run_ids": {"S": "[]"},
                }
            }
        )
        mock_client.put_item = AsyncMock()

        await backend.delete_schedule("sched_1")

        mock_client.put_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_schedules(self, mock_backend):
        """Test listing schedules."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "schedule_id": {"S": "sched_1"},
                        "workflow_name": {"S": "test"},
                        "spec": {"S": "0 9 * * *"},
                        "spec_type": {"S": "cron"},
                        "timezone": {"S": "UTC"},
                        "status": {"S": "active"},
                        "input_args": {"S": "[]"},
                        "input_kwargs": {"S": "{}"},
                        "overlap_policy": {"S": "skip"},
                        "created_at": {"S": now.isoformat()},
                        "running_run_ids": {"S": "[]"},
                    }
                ]
            }
        )

        schedules = await backend.list_schedules()

        assert len(schedules) == 1

    @pytest.mark.asyncio
    async def test_get_due_schedules(self, mock_backend):
        """Test getting due schedules uses GSI5."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.query = AsyncMock(
            return_value={
                "Items": [
                    {
                        "schedule_id": {"S": "sched_1"},
                        "workflow_name": {"S": "test"},
                        "spec": {"S": "0 9 * * *"},
                        "spec_type": {"S": "cron"},
                        "timezone": {"S": "UTC"},
                        "status": {"S": "active"},
                        "input_args": {"S": "[]"},
                        "input_kwargs": {"S": "{}"},
                        "overlap_policy": {"S": "skip"},
                        "created_at": {"S": now.isoformat()},
                        "next_run_time": {"S": now.isoformat()},
                        "running_run_ids": {"S": "[]"},
                    }
                ]
            }
        )

        result = await backend.get_due_schedules(now)

        call_args = mock_client.query.call_args
        assert call_args.kwargs["IndexName"] == "GSI5"
        assert call_args.kwargs["ExpressionAttributeValues"][":pk"]["S"] == "ACTIVE_SCHEDULES"
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_add_running_run(self, mock_backend):
        """Test adding a running run to schedule."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.get_item = AsyncMock(
            return_value={
                "Item": {
                    "schedule_id": {"S": "sched_1"},
                    "workflow_name": {"S": "test"},
                    "spec": {"S": "0 9 * * *"},
                    "spec_type": {"S": "cron"},
                    "timezone": {"S": "UTC"},
                    "status": {"S": "active"},
                    "input_args": {"S": "[]"},
                    "input_kwargs": {"S": "{}"},
                    "overlap_policy": {"S": "skip"},
                    "created_at": {"S": now.isoformat()},
                    "running_run_ids": {"S": "[]"},
                }
            }
        )
        mock_client.put_item = AsyncMock()

        await backend.add_running_run("sched_1", "run_1")

        mock_client.put_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_running_run(self, mock_backend):
        """Test removing a running run from schedule."""
        backend, mock_client = mock_backend
        now = datetime.now(UTC)

        mock_client.get_item = AsyncMock(
            return_value={
                "Item": {
                    "schedule_id": {"S": "sched_1"},
                    "workflow_name": {"S": "test"},
                    "spec": {"S": "0 9 * * *"},
                    "spec_type": {"S": "cron"},
                    "timezone": {"S": "UTC"},
                    "status": {"S": "active"},
                    "input_args": {"S": "[]"},
                    "input_kwargs": {"S": "{}"},
                    "overlap_policy": {"S": "skip"},
                    "created_at": {"S": now.isoformat()},
                    "running_run_ids": {"S": '["run_1", "run_2"]'},
                }
            }
        )
        mock_client.put_item = AsyncMock()

        await backend.remove_running_run("sched_1", "run_1")

        mock_client.put_item.assert_called_once()


class TestDynamoDBGSIQueries:
    """Test GSI-based queries."""

    @pytest.fixture
    def backend(self):
        """Create a DynamoDB backend instance."""
        return DynamoDBStorageBackend()

    @pytest.mark.asyncio
    async def test_gsi1_runs_by_status(self, backend):
        """Test that list_runs uses GSI1 for status queries."""
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={"Items": []})

        with patch.object(backend, "_get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_client)
            mock_context.__aexit__ = AsyncMock()
            mock_get_client.return_value = mock_context

            await backend.list_runs(status=RunStatus.RUNNING)

            call_args = mock_client.query.call_args
            assert call_args.kwargs["IndexName"] == "GSI1"

    @pytest.mark.asyncio
    async def test_gsi3_idempotency_key(self, backend):
        """Test that get_run_by_idempotency_key uses GSI3."""
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={"Items": []})

        with patch.object(backend, "_get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_client)
            mock_context.__aexit__ = AsyncMock()
            mock_get_client.return_value = mock_context

            await backend.get_run_by_idempotency_key("test_key")

            call_args = mock_client.query.call_args
            assert call_args.kwargs["IndexName"] == "GSI3"
            assert "IDEMPOTENCY#test_key" in str(call_args.kwargs["ExpressionAttributeValues"])

    @pytest.mark.asyncio
    async def test_gsi4_children(self, backend):
        """Test that get_children uses GSI4."""
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={"Items": []})

        with patch.object(backend, "_get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_client)
            mock_context.__aexit__ = AsyncMock()
            mock_get_client.return_value = mock_context

            await backend.get_children("parent_123")

            call_args = mock_client.query.call_args
            assert call_args.kwargs["IndexName"] == "GSI4"
            assert "PARENT#parent_123" in str(call_args.kwargs["ExpressionAttributeValues"])

    @pytest.mark.asyncio
    async def test_gsi5_due_schedules(self, backend):
        """Test that get_due_schedules uses GSI5."""
        now = datetime.now(UTC)
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={"Items": []})

        with patch.object(backend, "_get_client") as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_client)
            mock_context.__aexit__ = AsyncMock()
            mock_get_client.return_value = mock_context

            await backend.get_due_schedules(now)

            call_args = mock_client.query.call_args
            assert call_args.kwargs["IndexName"] == "GSI5"
            assert "ACTIVE_SCHEDULES" in str(call_args.kwargs["ExpressionAttributeValues"])
