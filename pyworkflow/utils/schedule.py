"""
Schedule time calculation utilities.

Handles cron expression parsing, interval calculation, and calendar-based scheduling.
Uses croniter for cron expression parsing.
"""

import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

from pyworkflow.storage.schemas import CalendarSpec, ScheduleSpec
from pyworkflow.utils.duration import parse_duration


def calculate_next_run_time(
    spec: ScheduleSpec,
    last_run: datetime | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """
    Calculate the next run time for a schedule.

    Args:
        spec: Schedule specification
        last_run: Last execution time (for interval-based)
        now: Current time (defaults to now in spec's timezone)

    Returns:
        Next run datetime (timezone-aware) or None if schedule has ended

    Examples:
        >>> spec = ScheduleSpec(cron="0 9 * * *")
        >>> next_run = calculate_next_run_time(spec)

        >>> spec = ScheduleSpec(interval="5m")
        >>> next_run = calculate_next_run_time(spec, last_run=datetime.now(UTC))
    """
    tz = ZoneInfo(spec.timezone)

    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    # Check if schedule has ended
    if spec.end_at:
        end_at = spec.end_at
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=tz)
        if now >= end_at:
            return None

    # Check if schedule hasn't started yet
    if spec.start_at:
        start_at = spec.start_at
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=tz)
        base_time = start_at if now < start_at else now
    else:
        base_time = now

    next_time: datetime | None = None

    if spec.cron:
        next_time = _next_cron_time(spec.cron, base_time, tz)
    elif spec.interval:
        next_time = _next_interval_time(spec.interval, last_run, base_time, tz)
    elif spec.calendar:
        next_time = _next_calendar_time(spec.calendar, base_time, tz)

    if next_time is None:
        return None

    # Apply jitter if specified
    if spec.jitter:
        jitter_seconds = parse_duration(spec.jitter)
        jitter = random.randint(0, jitter_seconds)
        next_time = next_time + timedelta(seconds=jitter)

    # Check if next_time is after end_at
    if spec.end_at:
        end_at = spec.end_at
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=tz)
        if next_time >= end_at:
            return None

    return next_time


def _next_cron_time(
    cron_expr: str,
    base_time: datetime,
    tz: ZoneInfo,
) -> datetime:
    """
    Calculate next cron execution time.

    Args:
        cron_expr: Cron expression (e.g., "0 9 * * *")
        base_time: Base time to calculate from
        tz: Timezone

    Returns:
        Next cron execution time
    """
    if base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=tz)

    cron = croniter(cron_expr, base_time)
    return cron.get_next(datetime)


def _next_interval_time(
    interval: str,
    last_run: datetime | None,
    base_time: datetime,
    tz: ZoneInfo,
) -> datetime:
    """
    Calculate next interval execution time.

    Args:
        interval: Interval string (e.g., "5m", "1h")
        last_run: Last run time
        base_time: Current time
        tz: Timezone

    Returns:
        Next interval execution time
    """
    interval_seconds = parse_duration(interval)

    if last_run is None:
        # First run - start immediately (at base_time)
        return base_time

    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=tz)

    next_time = last_run + timedelta(seconds=interval_seconds)

    if next_time < base_time:
        # Catch up - calculate how many intervals have passed
        elapsed = (base_time - last_run).total_seconds()
        intervals_passed = int(elapsed / interval_seconds)
        next_time = last_run + timedelta(seconds=interval_seconds * (intervals_passed + 1))

    return next_time


def _next_calendar_time(
    calendars: list[CalendarSpec],
    base_time: datetime,
    tz: ZoneInfo,
) -> datetime | None:
    """
    Calculate next calendar execution time.

    Args:
        calendars: List of calendar specifications
        base_time: Base time to calculate from
        tz: Timezone

    Returns:
        Next matching calendar time, or None if no match found
    """
    candidates: list[datetime] = []

    for cal in calendars:
        next_time = _next_calendar_match(cal, base_time, tz)
        if next_time:
            candidates.append(next_time)

    return min(candidates) if candidates else None


def _next_calendar_match(
    cal: CalendarSpec,
    base_time: datetime,
    tz: ZoneInfo,
) -> datetime | None:
    """
    Find next datetime matching a CalendarSpec.

    This function searches forward from base_time to find the next
    datetime that matches all specified constraints in the CalendarSpec.

    Args:
        cal: Calendar specification
        base_time: Base time to start searching from
        tz: Timezone

    Returns:
        Next matching datetime, or None if no match in next year
    """
    if base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=tz)

    # Start from the next second after base_time
    current = base_time + timedelta(seconds=1)

    # Set to the specified time
    current = current.replace(
        hour=cal.hour,
        minute=cal.minute,
        second=cal.second,
        microsecond=0,
    )

    # If this time has passed today, move to tomorrow
    if current <= base_time:
        current = current + timedelta(days=1)

    # Search up to 366 days ahead (one full year + leap day)
    max_iterations = 366
    for _ in range(max_iterations):
        matches = True

        # Check month constraint
        if cal.month is not None and current.month != cal.month:
            matches = False

        # Check day_of_month constraint
        if cal.day_of_month is not None and current.day != cal.day_of_month:
            matches = False

        # Check day_of_week constraint (0=Monday, 6=Sunday)
        if cal.day_of_week is not None and current.weekday() != cal.day_of_week:
            matches = False

        if matches:
            return current

        # Move to next day
        current = current + timedelta(days=1)
        current = current.replace(
            hour=cal.hour,
            minute=cal.minute,
            second=cal.second,
            microsecond=0,
        )

    # No match found within the search window
    return None


def calculate_backfill_times(
    spec: ScheduleSpec,
    start_time: datetime,
    end_time: datetime,
) -> list[datetime]:
    """
    Calculate all scheduled times in a time range for backfill.

    This is used to create runs for times that were missed
    (e.g., due to scheduler downtime).

    Args:
        spec: Schedule specification
        start_time: Start of backfill range
        end_time: End of backfill range

    Returns:
        List of scheduled execution times in chronological order

    Examples:
        >>> spec = ScheduleSpec(cron="0 * * * *")  # Every hour
        >>> times = calculate_backfill_times(
        ...     spec,
        ...     datetime(2024, 1, 1, 0, 0),
        ...     datetime(2024, 1, 1, 3, 0),
        ... )
        >>> len(times)  # 0:00, 1:00, 2:00 (3:00 is end, not included)
        3
    """
    times: list[datetime] = []

    # Use start_time as the reference point
    current = start_time

    # Disable jitter for backfill to get consistent times
    spec_no_jitter = ScheduleSpec(
        cron=spec.cron,
        interval=spec.interval,
        calendar=spec.calendar,
        timezone=spec.timezone,
        start_at=spec.start_at,
        end_at=spec.end_at,
        jitter=None,  # No jitter for backfill
    )

    # For interval-based, we need the last run before start_time
    last_run = None
    if spec.interval:
        # Calculate what the last run would have been before start_time
        interval_seconds = parse_duration(spec.interval)
        if spec.start_at and spec.start_at < start_time:
            # Calculate intervals since start_at
            elapsed = (start_time - spec.start_at).total_seconds()
            intervals = int(elapsed / interval_seconds)
            last_run = spec.start_at + timedelta(seconds=intervals * interval_seconds)
        else:
            last_run = start_time

    max_iterations = 10000  # Safety limit
    iteration = 0

    while iteration < max_iterations:
        next_time = calculate_next_run_time(spec_no_jitter, last_run, current)

        if next_time is None:
            break

        if next_time >= end_time:
            break

        times.append(next_time)

        # Move past this time
        current = next_time + timedelta(seconds=1)
        last_run = next_time
        iteration += 1

    return times


def validate_cron_expression(cron_expr: str) -> bool:
    """
    Validate a cron expression.

    Args:
        cron_expr: Cron expression to validate

    Returns:
        True if valid, False otherwise

    Examples:
        >>> validate_cron_expression("0 9 * * *")
        True
        >>> validate_cron_expression("invalid")
        False
    """
    try:
        croniter(cron_expr)
        return True
    except (ValueError, KeyError):
        return False


def describe_schedule(spec: ScheduleSpec) -> str:
    """
    Generate a human-readable description of a schedule.

    Args:
        spec: Schedule specification

    Returns:
        Human-readable description

    Examples:
        >>> spec = ScheduleSpec(cron="0 9 * * *")
        >>> describe_schedule(spec)
        'Cron: 0 9 * * * (UTC)'

        >>> spec = ScheduleSpec(interval="5m")
        >>> describe_schedule(spec)
        'Every 5m (UTC)'
    """
    tz_str = f" ({spec.timezone})"

    if spec.cron:
        return f"Cron: {spec.cron}{tz_str}"
    elif spec.interval:
        return f"Every {spec.interval}{tz_str}"
    elif spec.calendar:
        parts = []
        for cal in spec.calendar:
            part = f"{cal.hour:02d}:{cal.minute:02d}:{cal.second:02d}"
            if cal.day_of_week is not None:
                days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                part = f"{days[cal.day_of_week]} at {part}"
            elif cal.day_of_month is not None:
                part = f"Day {cal.day_of_month} at {part}"
            parts.append(part)
        return f"Calendar: {', '.join(parts)}{tz_str}"
    else:
        return "No schedule defined"
