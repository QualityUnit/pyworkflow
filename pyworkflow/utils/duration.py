"""
Duration parsing utilities.

Supports duration strings like:
- "30s" - 30 seconds
- "5m" - 5 minutes
- "2h" - 2 hours
- "3d" - 3 days
- "1w" - 1 week
"""

import re
from datetime import datetime, timedelta


def parse_duration(duration: str | int | timedelta | datetime) -> int:
    """
    Parse duration to seconds.

    Args:
        duration: Duration as:
            - str: Duration string ("5s", "2m", "1h")
            - int: Seconds
            - timedelta: Python timedelta
            - datetime: Future time (calculates delta from now)

    Returns:
        Number of seconds

    Raises:
        ValueError: If duration format is invalid

    Examples:
        >>> parse_duration("30s")
        30
        >>> parse_duration("5m")
        300
        >>> parse_duration("2h")
        7200
        >>> parse_duration(60)
        60
    """
    if isinstance(duration, str):
        return parse_duration_string(duration)

    if isinstance(duration, int):
        return duration

    if isinstance(duration, timedelta):
        return int(duration.total_seconds())

    if isinstance(duration, datetime):
        # Calculate seconds from now until that datetime
        delta = duration - datetime.utcnow()
        return max(0, int(delta.total_seconds()))

    raise TypeError(
        f"Duration must be str, int, timedelta, or datetime, got {type(duration).__name__}"
    )


def parse_duration_string(duration: str) -> int:
    """
    Parse duration string to seconds.

    Supported formats:
    - {number}s - seconds
    - {number}m - minutes
    - {number}h - hours
    - {number}d - days
    - {number}w - weeks

    Args:
        duration: Duration string

    Returns:
        Number of seconds

    Raises:
        ValueError: If format is invalid

    Examples:
        >>> parse_duration_string("30s")
        30
        >>> parse_duration_string("5m")
        300
        >>> parse_duration_string("2h")
        7200
        >>> parse_duration_string("3d")
        259200
        >>> parse_duration_string("1w")
        604800
    """
    pattern = r"^(\d+)([smhdw])$"
    match = re.match(pattern, duration.lower().strip())

    if not match:
        raise ValueError(
            f"Invalid duration format: '{duration}'. "
            f"Expected format: <number><unit> where unit is s/m/h/d/w "
            f"(e.g., '30s', '5m', '2h', '3d', '1w')"
        )

    value_str, unit = match.groups()
    value = int(value_str)

    # Conversion multipliers
    multipliers = {
        "s": 1,  # seconds
        "m": 60,  # minutes
        "h": 3600,  # hours
        "d": 86400,  # days
        "w": 604800,  # weeks
    }

    return value * multipliers[unit]


def format_duration(seconds: int) -> str:
    """
    Format seconds as human-readable duration string.

    Args:
        seconds: Number of seconds

    Returns:
        Human-readable duration string

    Examples:
        >>> format_duration(30)
        '30s'
        >>> format_duration(300)
        '5m'
        >>> format_duration(7200)
        '2h'
        >>> format_duration(259200)
        '3d'
        >>> format_duration(604800)
        '1w'
    """
    if seconds < 60:
        return f"{seconds}s"

    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"

    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h"

    if seconds < 604800:
        days = seconds // 86400
        return f"{days}d"

    weeks = seconds // 604800
    return f"{weeks}w"


def duration_to_timedelta(duration: str | int) -> timedelta:
    """
    Convert duration to Python timedelta.

    Args:
        duration: Duration as string or int (seconds)

    Returns:
        Python timedelta object

    Examples:
        >>> duration_to_timedelta("5m")
        timedelta(seconds=300)
        >>> duration_to_timedelta(300)
        timedelta(seconds=300)
    """
    seconds = parse_duration(duration)
    return timedelta(seconds=seconds)
