"""Service layer for calculating workflow metrics from event logs."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pyworkflow.engine.events import EventType
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import RunStatus


@dataclass
class MetricsSnapshot:
    """Point-in-time metrics calculated from event log."""

    # Counters: (label_tuple) -> count
    workflow_runs_total: dict[tuple[str, str], int] = field(default_factory=dict)
    steps_executed_total: dict[tuple[str, str], int] = field(default_factory=dict)
    step_retries_total: dict[tuple[str, str], int] = field(default_factory=dict)
    errors_total: dict[tuple[str, str], int] = field(default_factory=dict)

    # Gauges
    workflows_running: int = 0
    workflows_suspended: int = 0

    # Histograms: (label_tuple) -> list of durations in seconds
    workflow_durations: dict[str, list[float]] = field(default_factory=dict)
    step_durations: dict[tuple[str, str], list[float]] = field(default_factory=dict)

    # Metadata
    calculated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MetricsService:
    """Service for calculating and caching workflow metrics from event logs.

    This service aggregates metrics by querying the storage backend for runs
    and events within a lookback window. Results are cached with a configurable
    TTL to avoid recalculating on every request.

    Metrics are derived from:
    - Run records for status counts and workflow durations
    - Event logs for step execution, retry, and error counts
    """

    def __init__(
        self,
        storage: StorageBackend,
        cache_ttl_seconds: int = 15,
        lookback_hours: int = 24,
    ):
        """Initialize metrics service.

        Args:
            storage: Storage backend for accessing runs and events.
            cache_ttl_seconds: How long to cache metrics before recalculating.
            lookback_hours: How far back to look for metrics data.
        """
        self.storage = storage
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self.lookback = timedelta(hours=lookback_hours)
        self._cache: MetricsSnapshot | None = None
        self._cache_lock = asyncio.Lock()

    async def get_metrics(self, force_refresh: bool = False) -> MetricsSnapshot:
        """Get current metrics, using cache if valid.

        Args:
            force_refresh: If True, bypass cache and recalculate.

        Returns:
            MetricsSnapshot with current metrics.
        """
        async with self._cache_lock:
            if not force_refresh and self._is_cache_valid():
                return self._cache  # type: ignore[return-value]

            self._cache = await self._calculate_metrics()
            return self._cache

    def _is_cache_valid(self) -> bool:
        """Check if cached metrics are still valid."""
        if self._cache is None:
            return False
        age = datetime.now(UTC) - self._cache.calculated_at
        return age < self.cache_ttl

    async def _calculate_metrics(self) -> MetricsSnapshot:
        """Calculate metrics from storage.

        Queries runs and events within the lookback window and calculates
        all metrics including counters, gauges, and histograms.
        """
        snapshot = MetricsSnapshot()
        lookback_start = datetime.now(UTC) - self.lookback

        # Get runs for counter and gauge metrics
        await self._calculate_run_metrics(snapshot, lookback_start)

        # Get events for step-level metrics
        await self._calculate_event_metrics(snapshot, lookback_start)

        return snapshot

    async def _calculate_run_metrics(
        self,
        snapshot: MetricsSnapshot,
        since: datetime,
    ) -> None:
        """Calculate run-level metrics (counters, gauges, and workflow durations)."""
        cursor: str | None = None

        while True:
            runs, next_cursor = await self.storage.list_runs(
                start_time=since,
                limit=1000,
                cursor=cursor,
            )

            for run in runs:
                # Workflow runs total by status and workflow_name
                key = (run.status.value, run.workflow_name)
                snapshot.workflow_runs_total[key] = (
                    snapshot.workflow_runs_total.get(key, 0) + 1
                )

                # Gauges for current state
                if run.status == RunStatus.RUNNING:
                    snapshot.workflows_running += 1
                elif run.status == RunStatus.SUSPENDED:
                    snapshot.workflows_suspended += 1

                # Duration histogram for completed workflows
                if (
                    run.status == RunStatus.COMPLETED
                    and run.started_at
                    and run.completed_at
                ):
                    # Handle timezone-naive datetimes
                    started = run.started_at
                    completed = run.completed_at
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=UTC)
                    if completed.tzinfo is None:
                        completed = completed.replace(tzinfo=UTC)

                    duration = (completed - started).total_seconds()
                    if run.workflow_name not in snapshot.workflow_durations:
                        snapshot.workflow_durations[run.workflow_name] = []
                    snapshot.workflow_durations[run.workflow_name].append(duration)

            if not next_cursor:
                break
            cursor = next_cursor

    async def _calculate_event_metrics(
        self,
        snapshot: MetricsSnapshot,
        since: datetime,
    ) -> None:
        """Calculate event-level metrics (steps, retries, errors)."""
        cursor: str | None = None

        while True:
            runs, next_cursor = await self.storage.list_runs(
                start_time=since,
                limit=100,
                cursor=cursor,
            )

            for run in runs:
                events = await self.storage.get_events(run.run_id)
                self._process_events_for_metrics(snapshot, run.workflow_name, events)

            if not next_cursor:
                break
            cursor = next_cursor

    def _process_events_for_metrics(
        self,
        snapshot: MetricsSnapshot,
        workflow_name: str,
        events: list[Any],
    ) -> None:
        """Process events from a single run to update metrics."""
        step_starts: dict[str, datetime] = {}

        for event in events:
            if event.type == EventType.STEP_STARTED:
                step_id = event.data.get("step_id")
                step_name = event.data.get("step_name", "unknown")
                step_starts[step_id] = event.timestamp

                # Increment step execution counter
                key = (workflow_name, step_name)
                snapshot.steps_executed_total[key] = (
                    snapshot.steps_executed_total.get(key, 0) + 1
                )

            elif event.type == EventType.STEP_COMPLETED:
                step_id = event.data.get("step_id")
                step_name = event.data.get("step_name", "unknown")

                # Calculate step duration
                if step_id in step_starts:
                    start_time = step_starts[step_id]
                    end_time = event.timestamp

                    # Handle timezone-naive datetimes
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=UTC)
                    if end_time.tzinfo is None:
                        end_time = end_time.replace(tzinfo=UTC)

                    duration = (end_time - start_time).total_seconds()
                    key = (workflow_name, step_name)
                    if key not in snapshot.step_durations:
                        snapshot.step_durations[key] = []
                    snapshot.step_durations[key].append(duration)

            elif event.type == EventType.STEP_RETRYING:
                step_name = event.data.get("step_name", "unknown")
                key = (workflow_name, step_name)
                snapshot.step_retries_total[key] = (
                    snapshot.step_retries_total.get(key, 0) + 1
                )

            elif event.type == EventType.STEP_FAILED:
                error_type = event.data.get("error_type", "Unknown")
                key = (error_type, workflow_name)
                snapshot.errors_total[key] = snapshot.errors_total.get(key, 0) + 1

            elif event.type == EventType.WORKFLOW_FAILED:
                error_type = event.data.get("error_type", "Unknown")
                key = (error_type, workflow_name)
                snapshot.errors_total[key] = snapshot.errors_total.get(key, 0) + 1

    def get_cache_age_seconds(self) -> float:
        """Get the age of the current cache in seconds.

        Returns:
            Age in seconds, or 0 if no cache exists.
        """
        if self._cache is None:
            return 0.0
        age = datetime.now(UTC) - self._cache.calculated_at
        return age.total_seconds()
