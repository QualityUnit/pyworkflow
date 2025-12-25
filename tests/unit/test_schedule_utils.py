"""
Unit tests for schedule utility functions.
"""

from datetime import UTC, datetime, timedelta

from pyworkflow.storage.schemas import CalendarSpec, ScheduleSpec
from pyworkflow.utils.schedule import (
    calculate_backfill_times,
    calculate_next_run_time,
    describe_schedule,
    validate_cron_expression,
)


class TestValidateCronExpression:
    """Test cron expression validation."""

    def test_valid_cron_expressions(self):
        """Test valid cron expressions."""
        valid_expressions = [
            "* * * * *",  # Every minute
            "0 * * * *",  # Every hour
            "0 0 * * *",  # Every day at midnight
            "0 9 * * *",  # Every day at 9 AM
            "0 9 * * 1",  # Every Monday at 9 AM
            "0 0 1 * *",  # First day of every month
            "*/5 * * * *",  # Every 5 minutes
            "0 */4 * * *",  # Every 4 hours
            "0 9-17 * * 1-5",  # 9 AM to 5 PM, Monday to Friday
            "0 0 1,15 * *",  # 1st and 15th of every month
        ]

        for expr in valid_expressions:
            assert validate_cron_expression(expr), f"Expected '{expr}' to be valid"

    def test_invalid_cron_expressions(self):
        """Test invalid cron expressions."""
        invalid_expressions = [
            "",  # Empty
            "* * *",  # Too few fields
            "60 * * * *",  # Invalid minute
            "* 25 * * *",  # Invalid hour
            "* * 32 * *",  # Invalid day of month
            "* * * 13 *",  # Invalid month
            "* * * * 8",  # Invalid day of week
            "invalid",  # Not a cron expression
        ]

        for expr in invalid_expressions:
            assert not validate_cron_expression(expr), f"Expected '{expr}' to be invalid"


class TestCalculateNextRunTime:
    """Test next run time calculation."""

    def test_next_run_time_cron(self):
        """Test next run time calculation for cron expression."""
        spec = ScheduleSpec(cron="0 9 * * *")  # Daily at 9 AM
        now = datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, now=now)

        assert next_time is not None
        # Should be at 9 AM (today or tomorrow)
        assert next_time.hour == 9
        assert next_time.minute == 0

    def test_next_run_time_interval(self):
        """Test next run time calculation for interval."""
        spec = ScheduleSpec(interval="5m")
        now = datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, now=now)

        assert next_time is not None
        # First run with no last_run returns base_time (runs immediately)
        assert next_time == now

    def test_next_run_time_interval_with_last_run(self):
        """Test next run time calculation for interval with last run."""
        spec = ScheduleSpec(interval="10m")
        now = datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC)
        last_run = datetime(2024, 1, 15, 7, 55, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, last_run=last_run, now=now)

        assert next_time is not None
        # Should be 10 minutes after last run
        expected = last_run + timedelta(minutes=10)
        assert next_time == expected

    def test_next_run_time_calendar(self):
        """Test next run time calculation for calendar spec."""
        spec = ScheduleSpec(calendar=[CalendarSpec(day_of_month=1, hour=0, minute=0)])
        now = datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, now=now)

        assert next_time is not None
        # Should be first of next month
        assert next_time.day == 1
        assert next_time.hour == 0
        assert next_time.minute == 0

    def test_next_run_time_empty_spec(self):
        """Test next run time with empty spec returns None."""
        spec = ScheduleSpec()  # No cron, interval, or calendar

        next_time = calculate_next_run_time(spec)

        assert next_time is None

    def test_next_run_time_respects_start_at(self):
        """Test next run time respects start_at constraint."""
        start_at = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
        spec = ScheduleSpec(
            interval="1h",
            start_at=start_at,
        )
        now = datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, now=now)

        assert next_time is not None
        # Should not be before start_at
        assert next_time >= start_at

    def test_next_run_time_respects_end_at(self):
        """Test next run time returns None after end_at."""
        end_at = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        spec = ScheduleSpec(
            interval="1h",
            end_at=end_at,
        )
        now = datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, now=now)

        # Should be None since we're past end_at
        assert next_time is None


class TestCalculateBackfillTimes:
    """Test backfill time calculation."""

    def test_backfill_times_cron(self):
        """Test backfill times for cron expression."""
        spec = ScheduleSpec(cron="0 9 * * *")  # Daily at 9 AM
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)

        times = calculate_backfill_times(spec, start, end)

        # Should have 4 times (Jan 1, 2, 3, 4 at 9 AM)
        assert len(times) == 4
        for t in times:
            assert t.hour == 9
            assert t.minute == 0

    def test_backfill_times_interval(self):
        """Test backfill times for interval."""
        spec = ScheduleSpec(interval="1h")
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 5, 0, 0, tzinfo=UTC)

        times = calculate_backfill_times(spec, start, end)

        # Backfill starts from start and goes up to (but not including) end
        # hours 1, 2, 3, 4 (first interval happens at start+1h)
        assert len(times) >= 4

    def test_backfill_times_empty_range(self):
        """Test backfill times with empty range."""
        spec = ScheduleSpec(cron="0 9 * * *")
        start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)

        times = calculate_backfill_times(spec, start, end)

        # No 9 AM in this range
        assert len(times) == 0

    def test_backfill_times_invalid_range(self):
        """Test backfill times with start after end."""
        spec = ScheduleSpec(interval="1h")
        start = datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        times = calculate_backfill_times(spec, start, end)

        assert len(times) == 0


class TestDescribeSchedule:
    """Test schedule description generation."""

    def test_describe_cron(self):
        """Test description for cron expression."""
        spec = ScheduleSpec(cron="0 9 * * *")

        description = describe_schedule(spec)

        assert "cron" in description.lower() or "0 9 * * *" in description

    def test_describe_interval(self):
        """Test description for interval."""
        spec = ScheduleSpec(interval="5m")

        description = describe_schedule(spec)

        assert "5m" in description or "interval" in description.lower()

    def test_describe_calendar(self):
        """Test description for calendar spec."""
        spec = ScheduleSpec(calendar=[CalendarSpec(day_of_month=1, hour=0, minute=0)])

        description = describe_schedule(spec)

        assert description  # Should have some description

    def test_describe_empty_spec(self):
        """Test description for empty spec."""
        spec = ScheduleSpec()

        description = describe_schedule(spec)

        assert "no" in description.lower() or "unspecified" in description.lower()


class TestIntervalParsing:
    """Test interval duration parsing with last_run."""

    def test_seconds_interval(self):
        """Test seconds interval parsing."""
        spec = ScheduleSpec(interval="30s")
        now = datetime(2024, 1, 1, 0, 0, 30, tzinfo=UTC)
        last_run = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, last_run=last_run, now=now)

        expected = last_run + timedelta(seconds=30)
        assert next_time == expected

    def test_minutes_interval(self):
        """Test minutes interval parsing."""
        spec = ScheduleSpec(interval="15m")
        now = datetime(2024, 1, 1, 0, 15, 0, tzinfo=UTC)
        last_run = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, last_run=last_run, now=now)

        expected = last_run + timedelta(minutes=15)
        assert next_time == expected

    def test_hours_interval(self):
        """Test hours interval parsing."""
        spec = ScheduleSpec(interval="2h")
        now = datetime(2024, 1, 1, 2, 0, 0, tzinfo=UTC)
        last_run = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, last_run=last_run, now=now)

        expected = last_run + timedelta(hours=2)
        assert next_time == expected

    def test_days_interval(self):
        """Test days interval parsing."""
        spec = ScheduleSpec(interval="1d")
        now = datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)
        last_run = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, last_run=last_run, now=now)

        expected = last_run + timedelta(days=1)
        assert next_time == expected

    def test_first_interval_runs_immediately(self):
        """Test that first interval run (no last_run) runs at base_time."""
        spec = ScheduleSpec(interval="5m")
        now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        next_time = calculate_next_run_time(spec, now=now)

        # First run should be immediate (at now)
        assert next_time == now
