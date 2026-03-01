"""
Unit tests for the data retention feature.

Tests cover:
- InMemoryStorageBackend.delete_old_runs() correctness
- Config loading (env var + YAML) for data_retention_days
"""

import os
from datetime import UTC, datetime, timedelta

import pytest

from pyworkflow.storage.memory import InMemoryStorageBackend
from pyworkflow.storage.schemas import RunStatus, WorkflowRun


def _make_run(
    run_id: str,
    status: RunStatus,
    updated_at: datetime,
) -> WorkflowRun:
    return WorkflowRun(
        run_id=run_id,
        workflow_name="test_workflow",
        status=status,
        created_at=updated_at,
        updated_at=updated_at,
    )


class TestDeleteOldRuns:
    """Tests for InMemoryStorageBackend.delete_old_runs()."""

    @pytest.fixture()
    def storage(self):
        return InMemoryStorageBackend()

    @pytest.mark.asyncio
    async def test_deletes_old_terminal_runs(self, storage):
        """Runs in terminal states older than cutoff are deleted."""
        old_time = datetime.now(UTC) - timedelta(days=10)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        run = _make_run("run-old-completed", RunStatus.COMPLETED, old_time)
        await storage.create_run(run)

        count = await storage.delete_old_runs(cutoff)

        assert count == 1
        assert await storage.get_run("run-old-completed") is None

    @pytest.mark.asyncio
    async def test_does_not_delete_recent_terminal_runs(self, storage):
        """Terminal runs newer than cutoff are kept."""
        recent_time = datetime.now(UTC) - timedelta(days=1)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        run = _make_run("run-recent", RunStatus.COMPLETED, recent_time)
        await storage.create_run(run)

        count = await storage.delete_old_runs(cutoff)

        assert count == 0
        assert await storage.get_run("run-recent") is not None

    @pytest.mark.asyncio
    async def test_does_not_delete_active_runs(self, storage):
        """Active/non-terminal runs are never deleted even if old."""
        old_time = datetime.now(UTC) - timedelta(days=30)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        for status in (RunStatus.RUNNING, RunStatus.PENDING, RunStatus.SUSPENDED):
            run = _make_run(f"run-{status.value}", status, old_time)
            await storage.create_run(run)

        count = await storage.delete_old_runs(cutoff)

        assert count == 0
        for status in (RunStatus.RUNNING, RunStatus.PENDING, RunStatus.SUSPENDED):
            assert await storage.get_run(f"run-{status.value}") is not None

    @pytest.mark.asyncio
    async def test_deletes_all_terminal_statuses(self, storage):
        """All terminal statuses are eligible for deletion."""
        old_time = datetime.now(UTC) - timedelta(days=10)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        terminal_statuses = [
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.CONTINUED_AS_NEW,
            RunStatus.INTERRUPTED,
        ]
        for status in terminal_statuses:
            run = _make_run(f"run-{status.value}", status, old_time)
            await storage.create_run(run)

        count = await storage.delete_old_runs(cutoff)

        assert count == len(terminal_statuses)
        for status in terminal_statuses:
            assert await storage.get_run(f"run-{status.value}") is None

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self, storage):
        """Returns 0 when no runs match the criteria."""
        count = await storage.delete_old_runs(datetime.now(UTC))
        assert count == 0

    @pytest.mark.asyncio
    async def test_deletes_related_events(self, storage):
        """Events belonging to deleted runs are also removed."""
        from pyworkflow.engine.events import Event, EventType

        old_time = datetime.now(UTC) - timedelta(days=10)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        run = _make_run("run-with-events", RunStatus.COMPLETED, old_time)
        await storage.create_run(run)

        event = Event(
            run_id="run-with-events",
            type=EventType.WORKFLOW_STARTED,
            data={},
        )
        await storage.record_event(event)
        assert len(await storage.get_events("run-with-events")) == 1

        await storage.delete_old_runs(cutoff)

        assert await storage.get_events("run-with-events") == []

    @pytest.mark.asyncio
    async def test_deletes_related_steps(self, storage):
        """Steps belonging to deleted runs are also removed."""
        from datetime import UTC, datetime

        from pyworkflow.storage.schemas import StepExecution, StepStatus

        old_time = datetime.now(UTC) - timedelta(days=10)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        run = _make_run("run-with-steps", RunStatus.COMPLETED, old_time)
        await storage.create_run(run)

        step = StepExecution(
            step_id="step-1",
            run_id="run-with-steps",
            step_name="my_step",
            status=StepStatus.COMPLETED,
            created_at=old_time,
            updated_at=old_time,
        )
        await storage.create_step(step)
        assert await storage.get_step("step-1") is not None

        await storage.delete_old_runs(cutoff)

        assert await storage.get_step("step-1") is None

    @pytest.mark.asyncio
    async def test_does_not_affect_other_runs(self, storage):
        """Deleting old runs does not affect unrelated runs."""
        old_time = datetime.now(UTC) - timedelta(days=10)
        recent_time = datetime.now(UTC) - timedelta(days=1)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        old_run = _make_run("run-old", RunStatus.COMPLETED, old_time)
        active_run = _make_run("run-active", RunStatus.RUNNING, old_time)
        recent_run = _make_run("run-recent", RunStatus.COMPLETED, recent_time)

        for run in (old_run, active_run, recent_run):
            await storage.create_run(run)

        count = await storage.delete_old_runs(cutoff)

        assert count == 1
        assert await storage.get_run("run-old") is None
        assert await storage.get_run("run-active") is not None
        assert await storage.get_run("run-recent") is not None

    @pytest.mark.asyncio
    async def test_cancellation_flags_removed(self, storage):
        """Cancellation flags for deleted runs are cleaned up."""
        old_time = datetime.now(UTC) - timedelta(days=10)
        cutoff = datetime.now(UTC) - timedelta(days=5)

        run = _make_run("run-cancelled", RunStatus.CANCELLED, old_time)
        await storage.create_run(run)
        await storage.set_cancellation_flag("run-cancelled")
        assert await storage.check_cancellation_flag("run-cancelled") is True

        await storage.delete_old_runs(cutoff)

        assert await storage.check_cancellation_flag("run-cancelled") is False


class TestRetentionConfig:
    """Tests for data_retention_days configuration loading."""

    def setup_method(self):
        from pyworkflow.config import reset_config

        reset_config()

    def teardown_method(self):
        from pyworkflow.config import reset_config

        reset_config()
        # Clean env
        os.environ.pop("PYWORKFLOW_DATA_RETENTION_DAYS", None)

    def test_default_is_none(self):
        """data_retention_days defaults to None (keep forever)."""
        from pyworkflow.config import get_config

        config = get_config()
        assert config.data_retention_days is None

    def test_loaded_from_env_var(self):
        """data_retention_days is loaded from PYWORKFLOW_DATA_RETENTION_DAYS env var."""
        os.environ["PYWORKFLOW_DATA_RETENTION_DAYS"] = "30"

        from pyworkflow.config import _config_from_env_and_yaml

        config = _config_from_env_and_yaml()
        assert config.data_retention_days == 30

    def test_configure_accepts_data_retention_days(self):
        """configure() accepts data_retention_days kwarg."""
        import pyworkflow

        pyworkflow.configure(data_retention_days=90)
        from pyworkflow.config import get_config

        assert get_config().data_retention_days == 90

    def test_configure_rejects_unknown_key(self):
        """configure() still rejects unknown keys."""
        import pyworkflow

        with pytest.raises(ValueError, match="Unknown config option"):
            pyworkflow.configure(nonexistent_option=42)
