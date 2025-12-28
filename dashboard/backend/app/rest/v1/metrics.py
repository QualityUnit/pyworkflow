"""Prometheus metrics endpoint for PyWorkflow dashboard."""

from fastapi import APIRouter, Depends, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.dependencies.storage import get_storage
from app.services.metrics_service import MetricsService, MetricsSnapshot
from pyworkflow.storage.base import StorageBackend

router = APIRouter()

# Define histogram buckets for durations (in seconds)
DURATION_BUCKETS = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    float("inf"),
)

# Singleton instances
_metrics_service: MetricsService | None = None


async def get_metrics_service(
    storage: StorageBackend = Depends(get_storage),
) -> MetricsService:
    """Dependency to get or create MetricsService instance."""
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = MetricsService(storage)
    return _metrics_service


class PrometheusMetricsExporter:
    """Exports metrics to Prometheus format.

    Creates a fresh registry each time to avoid accumulating stale
    label combinations from deleted workflows or runs.
    """

    def __init__(self) -> None:
        """Initialize with a fresh registry."""
        self.registry = CollectorRegistry()
        self._setup_metrics()

    def _setup_metrics(self) -> None:
        """Set up Prometheus metric collectors."""
        # Counters
        self.workflow_runs_total = Counter(
            "pyworkflow_workflow_runs_total",
            "Total workflow runs by status and workflow name",
            ["status", "workflow_name"],
            registry=self.registry,
        )

        self.steps_executed_total = Counter(
            "pyworkflow_steps_executed_total",
            "Total steps executed by workflow and step name",
            ["workflow_name", "step_name"],
            registry=self.registry,
        )

        self.step_retries_total = Counter(
            "pyworkflow_step_retries_total",
            "Total step retries by workflow and step name",
            ["workflow_name", "step_name"],
            registry=self.registry,
        )

        self.errors_total = Counter(
            "pyworkflow_errors_total",
            "Total errors by type and workflow name",
            ["error_type", "workflow_name"],
            registry=self.registry,
        )

        # Gauges
        self.workflows_running = Gauge(
            "pyworkflow_workflows_running",
            "Currently running workflows",
            registry=self.registry,
        )

        self.workflows_suspended = Gauge(
            "pyworkflow_workflows_suspended",
            "Currently suspended workflows",
            registry=self.registry,
        )

        # Histograms
        self.workflow_duration = Histogram(
            "pyworkflow_workflow_duration_seconds",
            "Workflow execution duration in seconds",
            ["workflow_name"],
            buckets=DURATION_BUCKETS,
            registry=self.registry,
        )

        self.step_duration = Histogram(
            "pyworkflow_step_duration_seconds",
            "Step execution duration in seconds",
            ["workflow_name", "step_name"],
            buckets=DURATION_BUCKETS,
            registry=self.registry,
        )

    def update_from_snapshot(self, snapshot: MetricsSnapshot) -> None:
        """Update Prometheus metrics from a MetricsSnapshot.

        Note: This creates a new registry each time to avoid
        accumulating stale label combinations.

        Args:
            snapshot: MetricsSnapshot with calculated metrics.
        """
        # Reset registry to clear stale label combinations
        self.registry = CollectorRegistry()
        self._setup_metrics()

        # Counters - set values directly via internal _value
        for (status, workflow_name), count in snapshot.workflow_runs_total.items():
            self.workflow_runs_total.labels(
                status=status,
                workflow_name=workflow_name,
            )._value.set(count)

        for (workflow_name, step_name), count in snapshot.steps_executed_total.items():
            self.steps_executed_total.labels(
                workflow_name=workflow_name,
                step_name=step_name,
            )._value.set(count)

        for (workflow_name, step_name), count in snapshot.step_retries_total.items():
            self.step_retries_total.labels(
                workflow_name=workflow_name,
                step_name=step_name,
            )._value.set(count)

        for (error_type, workflow_name), count in snapshot.errors_total.items():
            self.errors_total.labels(
                error_type=error_type,
                workflow_name=workflow_name,
            )._value.set(count)

        # Gauges
        self.workflows_running.set(snapshot.workflows_running)
        self.workflows_suspended.set(snapshot.workflows_suspended)

        # Histograms - observe all recorded durations
        for workflow_name, durations in snapshot.workflow_durations.items():
            histogram = self.workflow_duration.labels(workflow_name=workflow_name)
            for duration in durations:
                histogram.observe(duration)

        for (workflow_name, step_name), durations in snapshot.step_durations.items():
            histogram = self.step_duration.labels(
                workflow_name=workflow_name,
                step_name=step_name,
            )
            for duration in durations:
                histogram.observe(duration)

    def generate(self) -> bytes:
        """Generate Prometheus metrics output.

        Returns:
            Prometheus text format metrics as bytes.
        """
        return generate_latest(self.registry)


@router.get("/metrics")
async def get_prometheus_metrics(
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> Response:
    """Prometheus metrics endpoint.

    Returns metrics in Prometheus text format for scraping.
    Metrics are cached and refreshed based on cache_ttl.

    Returns:
        Response with Prometheus text format metrics.
    """
    # Get metrics snapshot (uses caching internally)
    snapshot = await metrics_service.get_metrics()

    # Update exporter with snapshot
    exporter = PrometheusMetricsExporter()
    exporter.update_from_snapshot(snapshot)

    # Generate Prometheus format
    output = exporter.generate()

    return Response(
        content=output,
        media_type=CONTENT_TYPE_LATEST,
    )
