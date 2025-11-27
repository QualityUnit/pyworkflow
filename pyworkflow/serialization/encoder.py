"""
Custom encoding for complex Python types.

Supports serialization of:
- Primitives (int, str, bool, float, None)
- Collections (list, dict, tuple, set)
- Dates (datetime, date, timedelta)
- Special types (Decimal, Enum, Exception, bytes)
- Complex objects (via cloudpickle)
"""

import base64
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

import cloudpickle


class EnhancedJSONEncoder(json.JSONEncoder):
    """
    JSON encoder with support for additional Python types.

    Handles datetime, Decimal, Enum, Exception, bytes, and complex objects.
    """

    def default(self, obj: Any) -> Any:
        """
        Encode object to JSON-serializable form.

        Args:
            obj: Object to encode

        Returns:
            JSON-serializable representation
        """
        # Datetime types
        if isinstance(obj, datetime):
            return {
                "__type__": "datetime",
                "value": obj.isoformat(),
            }

        if isinstance(obj, date):
            return {
                "__type__": "date",
                "value": obj.isoformat(),
            }

        if isinstance(obj, timedelta):
            return {
                "__type__": "timedelta",
                "value": obj.total_seconds(),
            }

        # Numeric types
        if isinstance(obj, Decimal):
            return {
                "__type__": "decimal",
                "value": str(obj),
            }

        # Enum types
        if isinstance(obj, Enum):
            return {
                "__type__": "enum",
                "class": f"{obj.__class__.__module__}.{obj.__class__.__name__}",
                "value": obj.value,
            }

        # Exception types
        if isinstance(obj, Exception):
            return {
                "__type__": "exception",
                "class": obj.__class__.__name__,
                "message": str(obj),
                "args": obj.args,
            }

        # Binary data
        if isinstance(obj, bytes):
            return {
                "__type__": "bytes",
                "value": base64.b64encode(obj).decode("ascii"),
            }

        # Sets (convert to list)
        if isinstance(obj, set):
            return {
                "__type__": "set",
                "value": list(obj),
            }

        # Complex objects - fall back to cloudpickle
        try:
            return {
                "__type__": "cloudpickle",
                "value": base64.b64encode(cloudpickle.dumps(obj)).decode("ascii"),
            }
        except Exception as e:
            # If cloudpickle fails, raise serialization error
            raise TypeError(
                f"Object of type {type(obj).__name__} is not JSON serializable "
                f"and could not be pickled: {e}"
            ) from e


def serialize(obj: Any) -> str:
    """
    Serialize Python object to JSON string.

    Args:
        obj: Object to serialize

    Returns:
        JSON string

    Examples:
        >>> serialize({"name": "Alice", "age": 30})
        '{"name": "Alice", "age": 30}'

        >>> from datetime import datetime
        >>> serialize(datetime(2025, 1, 15, 10, 30))
        '{"__type__": "datetime", "value": "2025-01-15T10:30:00"}'
    """
    return json.dumps(obj, cls=EnhancedJSONEncoder)


def serialize_args(*args: Any) -> str:
    """
    Serialize positional arguments to JSON string.

    Args:
        *args: Positional arguments

    Returns:
        JSON string of list

    Examples:
        >>> serialize_args("hello", 42, True)
        '["hello", 42, true]'
    """
    return json.dumps(list(args), cls=EnhancedJSONEncoder)


def serialize_kwargs(**kwargs: Any) -> str:
    """
    Serialize keyword arguments to JSON string.

    Args:
        **kwargs: Keyword arguments

    Returns:
        JSON string of dict

    Examples:
        >>> serialize_kwargs(name="Alice", age=30)
        '{"name": "Alice", "age": 30}'
    """
    return json.dumps(kwargs, cls=EnhancedJSONEncoder)
