"""
Unit tests for schedule schemas and data models.
"""

from datetime import UTC, datetime

from pyworkflow.storage.schemas import (
    CalendarSpec,
    OverlapPolicy,
    Schedule,
    ScheduleSpec,
    ScheduleStatus,
)


class TestOverlapPolicy:
    """Test OverlapPolicy enum."""

    def test_overlap_policy_values(self):
        """Test all overlap policy values exist."""
        assert OverlapPolicy.SKIP.value == "skip"
        assert OverlapPolicy.BUFFER_ONE.value == "buffer_one"
        assert OverlapPolicy.BUFFER_ALL.value == "buffer_all"
        assert OverlapPolicy.CANCEL_OTHER.value == "cancel_other"
        assert OverlapPolicy.ALLOW_ALL.value == "allow_all"

    def test_overlap_policy_from_string(self):
        """Test creating OverlapPolicy from string value."""
        assert OverlapPolicy("skip") == OverlapPolicy.SKIP
        assert OverlapPolicy("buffer_one") == OverlapPolicy.BUFFER_ONE


class TestScheduleStatus:
    """Test ScheduleStatus enum."""

    def test_schedule_status_values(self):
        """Test all schedule status values exist."""
        assert ScheduleStatus.ACTIVE.value == "active"
        assert ScheduleStatus.PAUSED.value == "paused"
        assert ScheduleStatus.DELETED.value == "deleted"

    def test_schedule_status_from_string(self):
        """Test creating ScheduleStatus from string value."""
        assert ScheduleStatus("active") == ScheduleStatus.ACTIVE
        assert ScheduleStatus("paused") == ScheduleStatus.PAUSED


class TestCalendarSpec:
    """Test CalendarSpec dataclass."""

    def test_calendar_spec_defaults(self):
        """Test CalendarSpec default values."""
        spec = CalendarSpec()
        assert spec.second == 0
        assert spec.minute == 0
        assert spec.hour == 0
        assert spec.day_of_month is None
        assert spec.month is None
        assert spec.day_of_week is None

    def test_calendar_spec_with_values(self):
        """Test CalendarSpec with specific values."""
        spec = CalendarSpec(
            second=30,
            minute=15,
            hour=9,
            day_of_month=1,
            month=6,
            day_of_week=1,
        )
        assert spec.second == 30
        assert spec.minute == 15
        assert spec.hour == 9
        assert spec.day_of_month == 1
        assert spec.month == 6
        assert spec.day_of_week == 1


class TestScheduleSpec:
    """Test ScheduleSpec dataclass."""

    def test_schedule_spec_defaults(self):
        """Test ScheduleSpec default values."""
        spec = ScheduleSpec()
        assert spec.cron is None
        assert spec.interval is None
        assert spec.calendar is None
        assert spec.timezone == "UTC"
        assert spec.start_at is None
        assert spec.end_at is None
        assert spec.jitter is None

    def test_schedule_spec_with_cron(self):
        """Test ScheduleSpec with cron expression."""
        spec = ScheduleSpec(cron="0 9 * * *")
        assert spec.cron == "0 9 * * *"
        assert spec.interval is None

    def test_schedule_spec_with_interval(self):
        """Test ScheduleSpec with interval."""
        spec = ScheduleSpec(interval="5m")
        assert spec.interval == "5m"
        assert spec.cron is None

    def test_schedule_spec_with_calendar(self):
        """Test ScheduleSpec with calendar entries."""
        calendars = [
            CalendarSpec(day_of_month=1, hour=0, minute=0),
            CalendarSpec(day_of_month=15, hour=12, minute=0),
        ]
        spec = ScheduleSpec(calendar=calendars)
        assert len(spec.calendar) == 2
        assert spec.calendar[0].day_of_month == 1

    def test_schedule_spec_with_timezone(self):
        """Test ScheduleSpec with custom timezone."""
        spec = ScheduleSpec(cron="0 9 * * *", timezone="America/New_York")
        assert spec.timezone == "America/New_York"

    def test_schedule_spec_with_time_bounds(self):
        """Test ScheduleSpec with start_at and end_at."""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)

        spec = ScheduleSpec(
            cron="0 9 * * *",
            start_at=start,
            end_at=end,
        )
        assert spec.start_at == start
        assert spec.end_at == end


class TestSchedule:
    """Test Schedule dataclass."""

    def test_schedule_defaults(self):
        """Test Schedule default values."""
        spec = ScheduleSpec(cron="0 9 * * *")
        schedule = Schedule(
            schedule_id="test_sched",
            workflow_name="test_workflow",
            spec=spec,
        )

        assert schedule.schedule_id == "test_sched"
        assert schedule.workflow_name == "test_workflow"
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.args == "[]"
        assert schedule.kwargs == "{}"
        assert schedule.overlap_policy == OverlapPolicy.SKIP
        assert schedule.total_runs == 0
        assert schedule.successful_runs == 0
        assert schedule.failed_runs == 0
        assert schedule.skipped_runs == 0
        assert schedule.buffered_count == 0
        assert schedule.running_run_ids == []

    def test_schedule_with_all_values(self):
        """Test Schedule with all values specified."""
        spec = ScheduleSpec(cron="0 9 * * *")
        now = datetime.now(UTC)

        schedule = Schedule(
            schedule_id="sched_123",
            workflow_name="my_workflow",
            spec=spec,
            status=ScheduleStatus.PAUSED,
            args='["arg1", "arg2"]',
            kwargs='{"key": "value"}',
            overlap_policy=OverlapPolicy.BUFFER_ONE,
            created_at=now,
            updated_at=now,
            next_run_time=now,
            last_run_at=now,
            total_runs=10,
            successful_runs=8,
            failed_runs=2,
            skipped_runs=1,
            buffered_count=0,
            running_run_ids=["run_1", "run_2"],
        )

        assert schedule.schedule_id == "sched_123"
        assert schedule.status == ScheduleStatus.PAUSED
        assert schedule.overlap_policy == OverlapPolicy.BUFFER_ONE
        assert schedule.total_runs == 10
        assert schedule.successful_runs == 8
        assert schedule.failed_runs == 2
        assert len(schedule.running_run_ids) == 2

    def test_schedule_to_dict(self):
        """Test Schedule to_dict method."""
        spec = ScheduleSpec(cron="0 9 * * *", timezone="UTC")
        now = datetime.now(UTC)

        schedule = Schedule(
            schedule_id="sched_test",
            workflow_name="test_workflow",
            spec=spec,
            created_at=now,
        )

        data = schedule.to_dict()

        assert data["schedule_id"] == "sched_test"
        assert data["workflow_name"] == "test_workflow"
        assert data["status"] == "active"
        assert data["overlap_policy"] == "skip"
        assert "spec" in data
        assert data["spec"]["cron"] == "0 9 * * *"

    def test_schedule_from_dict(self):
        """Test Schedule from_dict method."""
        now = datetime.now(UTC)
        data = {
            "schedule_id": "sched_from_dict",
            "workflow_name": "dict_workflow",
            "spec": {
                "cron": "*/5 * * * *",
                "interval": None,
                "calendar": None,
                "timezone": "UTC",
                "start_at": None,
                "end_at": None,
                "jitter": None,
            },
            "status": "active",
            "args": "[]",
            "kwargs": "{}",
            "overlap_policy": "buffer_one",
            "created_at": now.isoformat(),
            "updated_at": None,
            "next_run_time": None,
            "last_run_at": None,
            "total_runs": 5,
            "successful_runs": 4,
            "failed_runs": 1,
            "skipped_runs": 0,
            "buffered_count": 0,
            "running_run_ids": [],
        }

        schedule = Schedule.from_dict(data)

        assert schedule.schedule_id == "sched_from_dict"
        assert schedule.workflow_name == "dict_workflow"
        assert schedule.spec.cron == "*/5 * * * *"
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.overlap_policy == OverlapPolicy.BUFFER_ONE
        assert schedule.total_runs == 5

    def test_schedule_roundtrip(self):
        """Test Schedule to_dict/from_dict roundtrip."""
        spec = ScheduleSpec(
            cron="0 */4 * * *",
            timezone="Europe/London",
        )
        now = datetime.now(UTC)

        original = Schedule(
            schedule_id="roundtrip_test",
            workflow_name="roundtrip_workflow",
            spec=spec,
            status=ScheduleStatus.ACTIVE,
            overlap_policy=OverlapPolicy.CANCEL_OTHER,
            created_at=now,
            total_runs=100,
            successful_runs=95,
            failed_runs=5,
        )

        # Convert to dict and back
        data = original.to_dict()
        restored = Schedule.from_dict(data)

        assert restored.schedule_id == original.schedule_id
        assert restored.workflow_name == original.workflow_name
        assert restored.spec.cron == original.spec.cron
        assert restored.spec.timezone == original.spec.timezone
        assert restored.status == original.status
        assert restored.overlap_policy == original.overlap_policy
        assert restored.total_runs == original.total_runs
        assert restored.successful_runs == original.successful_runs
        assert restored.failed_runs == original.failed_runs
