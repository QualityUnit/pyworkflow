"""Async helpers for Click commands."""

import asyncio
import functools
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def async_command(f: F) -> F:
    """
    Decorator to make Click commands work with async functions.

    Click doesn't natively support async functions, so this decorator
    wraps async functions with asyncio.run() to make them work with Click.

    Example:
        @click.command()
        @async_command
        async def my_command():
            result = await some_async_function()
            print(result)
    """

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(f(*args, **kwargs))

    return wrapper  # type: ignore[return-value]
