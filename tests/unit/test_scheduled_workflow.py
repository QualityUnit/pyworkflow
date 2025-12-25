"""
Unit tests for @scheduled_workflow decorator.
"""

import pytest

from pyworkflow.core.scheduled import (
    clear_scheduled_workflows,
    get_scheduled_workflow,
    list_scheduled_workflows,
    register_scheduled_workflow,
    scheduled_workflow,
    unregister_scheduled_workflow,
)
from pyworkflow.storage.schemas import OverlapPolicy, ScheduleSpec


@pytest.fixture(autouse=True)
def reset_scheduled_workflows():
    """Reset scheduled workflows registry before each test."""
    clear_scheduled_workflows()
    yield
    clear_scheduled_workflows()


class TestScheduledWorkflowDecorator:
    """Test the @scheduled_workflow decorator."""

    def test_scheduled_workflow_with_cron(self):
        """Test scheduled workflow with cron expression."""

        @scheduled_workflow(cron="0 9 * * *")
        async def daily_job():
            return "done"

        # Check workflow attributes
        assert hasattr(daily_job, "__workflow__")
        assert daily_job.__workflow__ is True
        assert daily_job.__workflow_name__ == "daily_job"

        # Check schedule attributes
        assert hasattr(daily_job, "__scheduled__")
        assert daily_job.__scheduled__ is True
        assert daily_job.__schedule_spec__.cron == "0 9 * * *"

    def test_scheduled_workflow_with_interval(self):
        """Test scheduled workflow with interval."""

        @scheduled_workflow(interval="5m")
        async def frequent_job():
            return "done"

        assert daily_job.__schedule_spec__.interval == "5m"

    def test_scheduled_workflow_with_custom_name(self):
        """Test scheduled workflow with custom name."""

        @scheduled_workflow(cron="0 0 * * *", name="custom_name")
        async def my_workflow():
            return "done"

        assert my_workflow.__workflow_name__ == "custom_name"

        # Should be registered with custom name
        meta = get_scheduled_workflow("custom_name")
        assert meta is not None
        assert meta.workflow_name == "custom_name"

    def test_scheduled_workflow_with_overlap_policy(self):
        """Test scheduled workflow with overlap policy."""

        @scheduled_workflow(
            cron="*/5 * * * *",
            overlap_policy=OverlapPolicy.BUFFER_ONE,
        )
        async def buffered_job():
            return "done"

        assert buffered_job.__overlap_policy__ == OverlapPolicy.BUFFER_ONE

        meta = get_scheduled_workflow("buffered_job")
        assert meta.overlap_policy == OverlapPolicy.BUFFER_ONE

    def test_scheduled_workflow_with_timezone(self):
        """Test scheduled workflow with timezone."""

        @scheduled_workflow(
            cron="0 9 * * *",
            timezone="America/New_York",
        )
        async def tz_job():
            return "done"

        assert tz_job.__schedule_spec__.timezone == "America/New_York"

    def test_scheduled_workflow_with_workflow_options(self):
        """Test scheduled workflow with workflow-specific options."""

        @scheduled_workflow(
            cron="0 0 * * 0",
            durable=True,
            max_duration="2h",
            recover_on_worker_loss=True,
            max_recovery_attempts=5,
        )
        async def full_options_job():
            return "done"

        assert full_options_job.__workflow_durable__ is True
        assert full_options_job.__workflow_max_duration__ == "2h"
        assert full_options_job.__workflow_recover_on_worker_loss__ is True
        assert full_options_job.__workflow_max_recovery_attempts__ == 5

    def test_scheduled_workflow_requires_schedule(self):
        """Test that scheduled_workflow requires at least one schedule type."""
        with pytest.raises(ValueError, match="requires at least one"):

            @scheduled_workflow()  # No cron, interval, or calendar
            async def invalid_job():
                return "done"

    def test_scheduled_workflow_registered_in_registry(self):
        """Test that scheduled workflow is registered in both registries."""
        from pyworkflow.core.registry import get_workflow

        @scheduled_workflow(cron="0 0 * * *")
        async def registered_job():
            return "done"

        # Should be in workflow registry
        workflow_meta = get_workflow("registered_job")
        assert workflow_meta is not None
        assert workflow_meta.name == "registered_job"

        # Should be in scheduled workflows registry
        schedule_meta = get_scheduled_workflow("registered_job")
        assert schedule_meta is not None
        assert schedule_meta.workflow_name == "registered_job"

    @pytest.mark.asyncio
    async def test_scheduled_workflow_execution(self):
        """Test that scheduled workflow can be executed normally."""

        @scheduled_workflow(interval="1h")
        async def executable_job(x: int):
            return x * 2

        result = await executable_job(5)
        assert result == 10


class TestScheduledWorkflowRegistry:
    """Test scheduled workflow registry functions."""

    def test_get_scheduled_workflow(self):
        """Test getting a scheduled workflow by name."""

        @scheduled_workflow(cron="0 9 * * *")
        async def get_test():
            pass

        meta = get_scheduled_workflow("get_test")
        assert meta is not None
        assert meta.workflow_name == "get_test"
        assert meta.spec.cron == "0 9 * * *"

    def test_get_scheduled_workflow_not_found(self):
        """Test getting non-existent scheduled workflow."""
        meta = get_scheduled_workflow("nonexistent")
        assert meta is None

    def test_list_scheduled_workflows(self):
        """Test listing all scheduled workflows."""

        @scheduled_workflow(cron="0 9 * * *")
        async def job1():
            pass

        @scheduled_workflow(interval="10m")
        async def job2():
            pass

        workflows = list_scheduled_workflows()
        assert len(workflows) == 2
        assert "job1" in workflows
        assert "job2" in workflows

    def test_register_scheduled_workflow_manually(self):
        """Test manually registering a scheduled workflow."""

        async def manual_job():
            return "done"

        spec = ScheduleSpec(cron="0 0 * * *")
        register_scheduled_workflow(
            "manual_job",
            spec,
            OverlapPolicy.SKIP,
            manual_job,
        )

        meta = get_scheduled_workflow("manual_job")
        assert meta is not None
        assert meta.workflow_name == "manual_job"

    def test_unregister_scheduled_workflow(self):
        """Test unregistering a scheduled workflow."""

        @scheduled_workflow(cron="0 0 * * *")
        async def unregister_test():
            pass

        # Should be registered
        assert get_scheduled_workflow("unregister_test") is not None

        # Unregister
        result = unregister_scheduled_workflow("unregister_test")
        assert result is True

        # Should no longer be registered
        assert get_scheduled_workflow("unregister_test") is None

    def test_unregister_scheduled_workflow_not_found(self):
        """Test unregistering non-existent workflow."""
        result = unregister_scheduled_workflow("nonexistent")
        assert result is False

    def test_clear_scheduled_workflows(self):
        """Test clearing all scheduled workflows."""

        @scheduled_workflow(cron="0 9 * * *")
        async def clear_test1():
            pass

        @scheduled_workflow(interval="5m")
        async def clear_test2():
            pass

        # Should have 2 workflows
        assert len(list_scheduled_workflows()) == 2

        # Clear
        clear_scheduled_workflows()

        # Should be empty
        assert len(list_scheduled_workflows()) == 0


class TestScheduledWorkflowMetadata:
    """Test ScheduledWorkflowMetadata dataclass."""

    def test_scheduled_workflow_metadata_attributes(self):
        """Test ScheduledWorkflowMetadata has expected attributes."""

        @scheduled_workflow(
            cron="0 9 * * *",
            overlap_policy=OverlapPolicy.CANCEL_OTHER,
        )
        async def metadata_test():
            pass

        meta = get_scheduled_workflow("metadata_test")

        assert meta.workflow_name == "metadata_test"
        assert meta.spec.cron == "0 9 * * *"
        assert meta.overlap_policy == OverlapPolicy.CANCEL_OTHER
        assert meta.func is not None
        assert callable(meta.func)


# Need to define daily_job at module level for test_scheduled_workflow_with_interval
@scheduled_workflow(interval="5m")
async def daily_job():
    return "done"
