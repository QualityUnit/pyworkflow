"""Tests for MetricsService."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.metrics_service import MetricsService, MetricsSnapshot
from pyworkflow.engine.events import Event, EventType
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


@pytest.fixture
def mock_storage():
    """Create a mock storage backend."""
    storage = AsyncMock()
    storage.list_runs = AsyncMock(return_value=([], None))
    storage.get_events = AsyncMock(return_value=[])
    return storage


@pytest.fixture
def metrics_service(mock_storage):
    """Create a MetricsService with mock storage."""
    return MetricsService(storage=mock_storage, cache_ttl_seconds=15, lookback_hours=24)


class TestMetricsSnapshot:
    """Tests for MetricsSnapshot dataclass."""

    def test_default_values(self):
        """Test MetricsSnapshot has correct defaults."""
        snapshot = MetricsSnapshot()
        assert snapshot.workflow_runs_total == {}
        assert snapshot.steps_executed_total == {}
        assert snapshot.step_retries_total == {}
        assert snapshot.errors_total == {}
        assert snapshot.workflows_running == 0
        assert snapshot.workflows_suspended == 0
        assert snapshot.workflow_durations == {}
        assert snapshot.step_durations == {}
        assert snapshot.calculated_at is not None


class TestMetricsServiceCaching:
    """Tests for MetricsService caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_is_populated_on_first_call(self, metrics_service, mock_storage):
        """Test metrics are calculated on first call."""
        await metrics_service.get_metrics()

        # Should have called storage
        mock_storage.list_runs.assert_called()

    @pytest.mark.asyncio
    async def test_cache_is_reused_within_ttl(self, metrics_service, mock_storage):
        """Test cached metrics are reused within TTL."""
        await metrics_service.get_metrics()
        call_count_after_first = mock_storage.list_runs.call_count

        await metrics_service.get_metrics()
        call_count_after_second = mock_storage.list_runs.call_count

        # Should not have called storage again (cache hit)
        assert call_count_after_first == call_count_after_second

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_cache(self, metrics_service, mock_storage):
        """Test force_refresh bypasses cache."""
        await metrics_service.get_metrics()
        call_count_after_first = mock_storage.list_runs.call_count

        await metrics_service.get_metrics(force_refresh=True)
        call_count_after_second = mock_storage.list_runs.call_count

        # Should have called storage again
        assert call_count_after_second > call_count_after_first

    def test_cache_age_seconds_returns_zero_when_no_cache(self, metrics_service):
        """Test cache_age_seconds returns 0 when no cache."""
        assert metrics_service.get_cache_age_seconds() == 0.0

    @pytest.mark.asyncio
    async def test_cache_age_seconds_after_calculation(self, metrics_service):
        """Test cache_age_seconds returns positive value after calculation."""
        await metrics_service.get_metrics()
        age = metrics_service.get_cache_age_seconds()
        assert age >= 0.0


class TestMetricsServiceCalculation:
    """Tests for metrics calculation."""

    @pytest.mark.asyncio
    async def test_empty_storage_returns_empty_metrics(self, metrics_service):
        """Test empty storage returns empty metrics."""
        snapshot = await metrics_service.get_metrics()

        assert snapshot.workflow_runs_total == {}
        assert snapshot.workflows_running == 0
        assert snapshot.workflows_suspended == 0

    @pytest.mark.asyncio
    async def test_workflow_runs_are_counted_by_status(self, mock_storage):
        """Test workflow runs are counted by status."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
            ),
            WorkflowRun(
                run_id="run_2",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
            ),
            WorkflowRun(
                run_id="run_3",
                workflow_name="test_workflow",
                status=RunStatus.RUNNING,
                created_at=now,
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        assert snapshot.workflow_runs_total.get(("completed", "test_workflow")) == 2
        assert snapshot.workflow_runs_total.get(("running", "test_workflow")) == 1
        assert snapshot.workflows_running == 1

    @pytest.mark.asyncio
    async def test_workflow_durations_are_calculated(self, mock_storage):
        """Test workflow durations are calculated for completed runs."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now - timedelta(hours=1),
                started_at=now - timedelta(minutes=10),
                completed_at=now - timedelta(minutes=5),
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        assert "test_workflow" in snapshot.workflow_durations
        assert len(snapshot.workflow_durations["test_workflow"]) == 1
        # Duration should be 5 minutes = 300 seconds
        assert snapshot.workflow_durations["test_workflow"][0] == 300.0

    @pytest.mark.asyncio
    async def test_step_events_are_counted(self, mock_storage):
        """Test step execution events are counted."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
            ),
        ]
        events = [
            Event(
                run_id="run_1",
                type=EventType.STEP_STARTED,
                timestamp=now - timedelta(seconds=10),
                data={"step_id": "step_1", "step_name": "validate"},
            ),
            Event(
                run_id="run_1",
                type=EventType.STEP_COMPLETED,
                timestamp=now - timedelta(seconds=5),
                data={"step_id": "step_1", "step_name": "validate"},
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)
        mock_storage.get_events.return_value = events

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        assert snapshot.steps_executed_total.get(("test_workflow", "validate")) == 1

    @pytest.mark.asyncio
    async def test_step_durations_are_calculated(self, mock_storage):
        """Test step durations are calculated from events."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
            ),
        ]
        events = [
            Event(
                run_id="run_1",
                type=EventType.STEP_STARTED,
                timestamp=now - timedelta(seconds=10),
                data={"step_id": "step_1", "step_name": "validate"},
            ),
            Event(
                run_id="run_1",
                type=EventType.STEP_COMPLETED,
                timestamp=now - timedelta(seconds=5),
                data={"step_id": "step_1", "step_name": "validate"},
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)
        mock_storage.get_events.return_value = events

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        key = ("test_workflow", "validate")
        assert key in snapshot.step_durations
        assert len(snapshot.step_durations[key]) == 1
        # Duration should be 5 seconds
        assert snapshot.step_durations[key][0] == 5.0

    @pytest.mark.asyncio
    async def test_step_retries_are_counted(self, mock_storage):
        """Test step retry events are counted."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
            ),
        ]
        events = [
            Event(
                run_id="run_1",
                type=EventType.STEP_RETRYING,
                timestamp=now,
                data={"step_id": "step_1", "step_name": "flaky_step"},
            ),
            Event(
                run_id="run_1",
                type=EventType.STEP_RETRYING,
                timestamp=now,
                data={"step_id": "step_1", "step_name": "flaky_step"},
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)
        mock_storage.get_events.return_value = events

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        assert snapshot.step_retries_total.get(("test_workflow", "flaky_step")) == 2

    @pytest.mark.asyncio
    async def test_errors_are_counted(self, mock_storage):
        """Test error events are counted."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.FAILED,
                created_at=now,
            ),
        ]
        events = [
            Event(
                run_id="run_1",
                type=EventType.STEP_FAILED,
                timestamp=now,
                data={"step_id": "step_1", "error_type": "ValueError"},
            ),
            Event(
                run_id="run_1",
                type=EventType.WORKFLOW_FAILED,
                timestamp=now,
                data={"error_type": "StepError"},
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)
        mock_storage.get_events.return_value = events

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        assert snapshot.errors_total.get(("ValueError", "test_workflow")) == 1
        assert snapshot.errors_total.get(("StepError", "test_workflow")) == 1

    @pytest.mark.asyncio
    async def test_suspended_workflows_are_counted(self, mock_storage):
        """Test suspended workflows are counted in gauge."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.SUSPENDED,
                created_at=now,
            ),
            WorkflowRun(
                run_id="run_2",
                workflow_name="test_workflow",
                status=RunStatus.SUSPENDED,
                created_at=now,
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        assert snapshot.workflows_suspended == 2


class TestMetricsServiceEdgeCases:
    """Edge case tests for MetricsService."""

    @pytest.fixture
    def mock_storage(self):
        """Create a mock storage backend."""
        storage = AsyncMock()
        storage.list_runs = AsyncMock(return_value=([], None))
        storage.get_events = AsyncMock(return_value=[])
        return storage

    @pytest.mark.asyncio
    async def test_workflow_without_started_at(self, mock_storage):
        """Test handling workflow with no started_at timestamp."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
                # No started_at
                completed_at=now,
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        # Should still count the workflow
        assert snapshot.workflow_runs_total.get(("completed", "test_workflow")) == 1
        # But no duration should be recorded
        assert "test_workflow" not in snapshot.workflow_durations

    @pytest.mark.asyncio
    async def test_workflow_without_completed_at(self, mock_storage):
        """Test handling workflow with no completed_at timestamp."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
                started_at=now,
                # No completed_at
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        # Should still count the workflow
        assert snapshot.workflow_runs_total.get(("completed", "test_workflow")) == 1
        # But no duration should be recorded
        assert "test_workflow" not in snapshot.workflow_durations

    @pytest.mark.asyncio
    async def test_step_started_counts_execution(self, mock_storage):
        """Test STEP_STARTED event counts as step execution."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.RUNNING,
                created_at=now,
            ),
        ]
        events = [
            Event(
                run_id="run_1",
                type=EventType.STEP_STARTED,
                timestamp=now,
                data={"step_id": "step_1", "step_name": "running_step"},
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)
        mock_storage.get_events.return_value = events

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        # Step should be counted as executed on start
        assert snapshot.steps_executed_total.get(("test_workflow", "running_step")) == 1
        # No duration should be calculated without completion
        assert ("test_workflow", "running_step") not in snapshot.step_durations

    @pytest.mark.asyncio
    async def test_step_completed_only_calculates_duration(self, mock_storage):
        """Test STEP_COMPLETED without STEP_STARTED doesn't count execution."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
            ),
        ]
        events = [
            Event(
                run_id="run_1",
                type=EventType.STEP_COMPLETED,
                timestamp=now,
                data={"step_id": "step_1", "step_name": "orphan_step"},
            ),
            # No STEP_STARTED event
        ]
        mock_storage.list_runs.return_value = (runs, None)
        mock_storage.get_events.return_value = events

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        # Step should not be counted (only STEP_STARTED counts)
        assert snapshot.steps_executed_total.get(("test_workflow", "orphan_step")) is None
        # No duration without start time
        assert ("test_workflow", "orphan_step") not in snapshot.step_durations

    @pytest.mark.asyncio
    async def test_multiple_workflows_same_name(self, mock_storage):
        """Test metrics aggregation for same workflow name."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="shared_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
                started_at=now - timedelta(seconds=10),
                completed_at=now,
            ),
            WorkflowRun(
                run_id="run_2",
                workflow_name="shared_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
                started_at=now - timedelta(seconds=20),
                completed_at=now,
            ),
            WorkflowRun(
                run_id="run_3",
                workflow_name="shared_workflow",
                status=RunStatus.FAILED,
                created_at=now,
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        # Should aggregate by status
        assert snapshot.workflow_runs_total.get(("completed", "shared_workflow")) == 2
        assert snapshot.workflow_runs_total.get(("failed", "shared_workflow")) == 1

        # Duration should have 2 entries
        assert len(snapshot.workflow_durations.get("shared_workflow", [])) == 2

    @pytest.mark.asyncio
    async def test_error_without_error_type(self, mock_storage):
        """Test error event missing error_type field."""
        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.FAILED,
                created_at=now,
            ),
        ]
        events = [
            Event(
                run_id="run_1",
                type=EventType.STEP_FAILED,
                timestamp=now,
                data={"step_id": "step_1"},  # No error_type
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)
        mock_storage.get_events.return_value = events

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        # Should handle gracefully with "Unknown" error type
        assert snapshot.errors_total.get(("Unknown", "test_workflow")) == 1

    @pytest.mark.asyncio
    async def test_cache_expiration(self, mock_storage):
        """Test cache expires after TTL."""
        import time

        # Use very short TTL
        service = MetricsService(mock_storage, cache_ttl_seconds=0.1)

        await service.get_metrics()
        first_call_count = mock_storage.list_runs.call_count

        # Wait for cache to expire
        time.sleep(0.15)

        await service.get_metrics()
        second_call_count = mock_storage.list_runs.call_count

        # Should have called storage again after expiration
        assert second_call_count > first_call_count
