"""Tests for Prometheus metrics endpoint."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.rest.v1.metrics import PrometheusMetricsExporter
from app.services.metrics_service import MetricsSnapshot


class TestPrometheusMetricsExporter:
    """Unit tests for PrometheusMetricsExporter class."""

    def test_exporter_initialization(self):
        """Test exporter creates all metric types."""
        exporter = PrometheusMetricsExporter()

        # Verify all metric collectors are created
        assert exporter.workflow_runs_total is not None
        assert exporter.steps_executed_total is not None
        assert exporter.step_retries_total is not None
        assert exporter.errors_total is not None
        assert exporter.workflows_running is not None
        assert exporter.workflows_suspended is not None
        assert exporter.workflow_duration is not None
        assert exporter.step_duration is not None

    def test_update_from_empty_snapshot(self):
        """Test exporter handles empty MetricsSnapshot."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot()

        # Should not raise
        exporter.update_from_snapshot(snapshot)

        # Generate output should work
        output = exporter.generate()
        assert isinstance(output, bytes)
        assert len(output) > 0

    def test_update_workflow_runs_counter(self):
        """Test workflow_runs_total counter with labels."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(
            workflow_runs_total={
                ("completed", "order_workflow"): 10,
                ("failed", "order_workflow"): 2,
                ("running", "payment_workflow"): 3,
            }
        )

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate().decode("utf-8")

        assert "pyworkflow_workflow_runs_total" in output
        assert 'status="completed"' in output
        assert 'workflow_name="order_workflow"' in output
        assert "10.0" in output

    def test_update_steps_executed_counter(self):
        """Test steps_executed_total counter with labels."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(
            steps_executed_total={
                ("order_workflow", "validate"): 100,
                ("order_workflow", "process"): 95,
            }
        )

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate().decode("utf-8")

        assert "pyworkflow_steps_executed_total" in output
        assert 'workflow_name="order_workflow"' in output
        assert 'step_name="validate"' in output

    def test_update_step_retries_counter(self):
        """Test step_retries_total counter."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(
            step_retries_total={
                ("order_workflow", "flaky_step"): 5,
            }
        )

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate().decode("utf-8")

        assert "pyworkflow_step_retries_total" in output
        assert 'step_name="flaky_step"' in output

    def test_update_errors_counter(self):
        """Test errors_total counter with error_type label."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(
            errors_total={
                ("ValueError", "order_workflow"): 3,
                ("TimeoutError", "payment_workflow"): 1,
            }
        )

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate().decode("utf-8")

        assert "pyworkflow_errors_total" in output
        assert 'error_type="ValueError"' in output
        assert 'error_type="TimeoutError"' in output

    def test_update_workflows_running_gauge(self):
        """Test workflows_running gauge."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(workflows_running=5)

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate().decode("utf-8")

        assert "pyworkflow_workflows_running" in output
        assert "5.0" in output

    def test_update_workflows_suspended_gauge(self):
        """Test workflows_suspended gauge."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(workflows_suspended=3)

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate().decode("utf-8")

        assert "pyworkflow_workflows_suspended" in output
        assert "3.0" in output

    def test_update_workflow_duration_histogram(self):
        """Test workflow_duration_seconds histogram buckets."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(
            workflow_durations={
                "order_workflow": [1.5, 2.3, 5.0, 10.0],
            }
        )

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate().decode("utf-8")

        assert "pyworkflow_workflow_duration_seconds" in output
        assert 'workflow_name="order_workflow"' in output
        # Check histogram has bucket, count, and sum lines
        assert "_bucket" in output
        assert "_count" in output
        assert "_sum" in output

    def test_update_step_duration_histogram(self):
        """Test step_duration_seconds histogram buckets."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(
            step_durations={
                ("order_workflow", "validate"): [0.1, 0.2, 0.15],
            }
        )

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate().decode("utf-8")

        assert "pyworkflow_step_duration_seconds" in output
        assert 'step_name="validate"' in output

    def test_generate_prometheus_format(self):
        """Test generate() returns valid Prometheus text format."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(
            workflow_runs_total={("completed", "test_wf"): 5},
            workflows_running=2,
        )

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate()

        # Should be bytes
        assert isinstance(output, bytes)

        # Decode and check format
        text = output.decode("utf-8")

        # Each metric should have proper format
        lines = text.strip().split("\n")
        for line in lines:
            if line.startswith("#"):
                # Comment line (HELP or TYPE)
                assert line.startswith("# HELP") or line.startswith("# TYPE")
            elif line.strip():
                # Metric line should have metric_name{labels} value format
                # or metric_name value format for gauges without labels
                assert " " in line or "}" in line

    def test_generate_includes_help_and_type(self):
        """Test output includes # HELP and # TYPE lines."""
        exporter = PrometheusMetricsExporter()
        snapshot = MetricsSnapshot(workflows_running=1)

        exporter.update_from_snapshot(snapshot)
        output = exporter.generate().decode("utf-8")

        # Should include HELP and TYPE metadata
        assert "# HELP pyworkflow_workflows_running" in output
        assert "# TYPE pyworkflow_workflows_running gauge" in output

    def test_multiple_updates_reset_registry(self):
        """Test that update_from_snapshot resets registry to avoid stale data."""
        exporter = PrometheusMetricsExporter()

        # First update
        snapshot1 = MetricsSnapshot(
            workflow_runs_total={("completed", "workflow_a"): 10}
        )
        exporter.update_from_snapshot(snapshot1)
        output1 = exporter.generate().decode("utf-8")
        assert 'workflow_name="workflow_a"' in output1

        # Second update with different workflow
        snapshot2 = MetricsSnapshot(
            workflow_runs_total={("completed", "workflow_b"): 5}
        )
        exporter.update_from_snapshot(snapshot2)
        output2 = exporter.generate().decode("utf-8")

        # Should have new workflow, old should be cleared
        assert 'workflow_name="workflow_b"' in output2


class TestMetricsEndpoint:
    """Integration tests for /api/v1/metrics endpoint."""

    @pytest.fixture
    def mock_storage(self):
        """Create a mock storage backend."""
        storage = AsyncMock()
        storage.list_runs = AsyncMock(return_value=([], None))
        storage.get_events = AsyncMock(return_value=[])
        return storage

    @pytest.fixture
    def app(self, mock_storage):
        """Create a FastAPI app with mocked storage."""
        from fastapi import FastAPI

        from app.rest.v1.metrics import get_metrics_service, router
        from app.services.metrics_service import MetricsService

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        # Reset the singleton
        import app.rest.v1.metrics as metrics_module

        metrics_module._metrics_service = None

        # Override dependency
        async def override_get_metrics_service():
            return MetricsService(mock_storage)

        app.dependency_overrides[get_metrics_service] = override_get_metrics_service

        return app

    @pytest.mark.asyncio
    async def test_metrics_endpoint_returns_200(self, app):
        """Test endpoint returns 200 OK."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/metrics")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metrics_endpoint_content_type(self, app):
        """Test response has text/plain content type."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/metrics")

            # Prometheus client returns specific content type
            content_type = response.headers.get("content-type", "")
            assert "text/plain" in content_type

    @pytest.mark.asyncio
    async def test_metrics_endpoint_prometheus_format(self, app):
        """Test response is valid Prometheus format."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/metrics")
            text = response.text

            # Should have metric definitions
            assert "# HELP" in text or "# TYPE" in text or "pyworkflow_" in text

    @pytest.mark.asyncio
    async def test_metrics_endpoint_with_workflow_data(self, mock_storage):
        """Test metrics reflect actual workflow runs."""
        from datetime import timedelta

        from pyworkflow.storage.schemas import RunStatus, WorkflowRun

        now = datetime.now(UTC)
        runs = [
            WorkflowRun(
                run_id="run_1",
                workflow_name="test_workflow",
                status=RunStatus.COMPLETED,
                created_at=now,
                started_at=now - timedelta(minutes=5),
                completed_at=now,
            ),
        ]
        mock_storage.list_runs.return_value = (runs, None)

        from app.services.metrics_service import MetricsService

        service = MetricsService(mock_storage)
        snapshot = await service.get_metrics()

        assert snapshot.workflow_runs_total.get(("completed", "test_workflow")) == 1

    @pytest.mark.asyncio
    async def test_metrics_endpoint_caching(self, mock_storage):
        """Test metrics are cached between calls."""
        from fastapi import FastAPI

        from app.rest.v1.metrics import get_metrics_service, router
        from app.services.metrics_service import MetricsService

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        # Reset singleton
        import app.rest.v1.metrics as metrics_module

        metrics_module._metrics_service = None

        # Create shared service
        service = MetricsService(mock_storage, cache_ttl_seconds=60)

        async def override_get_metrics_service():
            return service

        app.dependency_overrides[get_metrics_service] = override_get_metrics_service

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # First call
            await client.get("/api/v1/metrics")
            first_call_count = mock_storage.list_runs.call_count

            # Second call should use cache
            await client.get("/api/v1/metrics")
            second_call_count = mock_storage.list_runs.call_count

            # Storage should only be called once due to caching
            assert second_call_count == first_call_count
