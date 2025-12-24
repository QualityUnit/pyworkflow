"""
Custom decoding for complex Python types.

Reverses the encoding performed by encoder.py to reconstruct Python objects.
"""

import base64
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import cloudpickle


def enhanced_json_decoder(dct: dict) -> Any:
    """
    Decode custom JSON types back to Python objects.

    Args:
        dct: Dictionary from JSON parsing

    Returns:
        Decoded Python object
    """
    if "__type__" not in dct:
        return dct

    type_name = dct["__type__"]

    # Datetime types
    if type_name == "datetime":
        return datetime.fromisoformat(dct["value"])

    if type_name == "date":
        return date.fromisoformat(dct["value"])

    if type_name == "timedelta":
        return timedelta(seconds=dct["value"])

    # Numeric types
    if type_name == "decimal":
        return Decimal(dct["value"])

    # Enum types
    if type_name == "enum":
        # Dynamically import and reconstruct enum
        module_name, class_name = dct["class"].rsplit(".", 1)
        try:
            module = __import__(module_name, fromlist=[class_name])
            enum_class = getattr(module, class_name)
            return enum_class(dct["value"])
        except (ImportError, AttributeError, ValueError):
            # If enum can't be reconstructed, return the dict
            return dct

    # Exception types
    if type_name == "exception":
        # Reconstruct exception
        exc_class_name = dct["class"]
        try:
            # Try to get exception class from builtins
            exc_class = getattr(__builtins__, exc_class_name, Exception)
        except (AttributeError, TypeError):
            exc_class = Exception

        try:
            return exc_class(*dct.get("args", []))
        except Exception:
            # If reconstruction fails, return generic exception
            return Exception(dct.get("message", "Unknown error"))

    # Binary data
    if type_name == "bytes":
        return base64.b64decode(dct["value"])

    # Sets
    if type_name == "set":
        return set(dct["value"])

    # Cloudpickle objects
    if type_name == "cloudpickle":
        try:
            return cloudpickle.loads(base64.b64decode(dct["value"]))
        except Exception:
            # If unpickling fails, return the dict
            return dct

    # Unknown type - return as-is
    return dct


def deserialize(json_str: str) -> Any:
    """
    Deserialize JSON string to Python object.

    Args:
        json_str: JSON string

    Returns:
        Deserialized Python object

    Examples:
        >>> deserialize('{"name": "Alice", "age": 30}')
        {'name': 'Alice', 'age': 30}

        >>> deserialize('{"__type__": "datetime", "value": "2025-01-15T10:30:00"}')
        datetime.datetime(2025, 1, 15, 10, 30)
    """
    return json.loads(json_str, object_hook=enhanced_json_decoder)


def deserialize_args(json_str: str) -> tuple[Any, ...]:
    """
    Deserialize JSON string to tuple of arguments.

    Args:
        json_str: JSON string of list

    Returns:
        Tuple of arguments

    Examples:
        >>> deserialize_args('["hello", 42, true]')
        ('hello', 42, True)
    """
    args_list = json.loads(json_str, object_hook=enhanced_json_decoder)
    return tuple(args_list) if isinstance(args_list, list) else ()


def deserialize_kwargs(json_str: str) -> dict:
    """
    Deserialize JSON string to dictionary of keyword arguments.

    Args:
        json_str: JSON string of dict

    Returns:
        Dictionary of keyword arguments

    Examples:
        >>> deserialize_kwargs('{"name": "Alice", "age": 30}')
        {'name': 'Alice', 'age': 30}
    """
    kwargs_dict = json.loads(json_str, object_hook=enhanced_json_decoder)
    return kwargs_dict if isinstance(kwargs_dict, dict) else {}
