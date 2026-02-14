"""
The @tool decorator for creating langchain-compatible StructuredTool instances.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool


def tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    return_direct: bool = False,
    args_schema: type | None = None,
    infer_schema: bool = True,
    parse_docstring: bool = False,
    register: bool = True,
) -> Any:
    """Decorator that creates a langchain StructuredTool and optionally registers it.

    Can be used as ``@tool`` or ``@tool(name="foo", ...)``.

    Args:
        func: The function to wrap (provided when used without parentheses).
        name: Override the tool name (defaults to function name).
        description: Override the tool description (defaults to docstring).
        return_direct: If True, the tool result is returned directly to the user.
        args_schema: Optional Pydantic model for argument validation.
        infer_schema: Whether to infer the schema from the function signature.
        parse_docstring: Whether to parse the docstring for argument descriptions.
        register: If True (default), auto-register in the global ToolRegistry.
    """

    def decorator(fn: Callable) -> StructuredTool:
        kwargs: dict[str, Any] = {
            "return_direct": return_direct,
            "infer_schema": infer_schema,
            "parse_docstring": parse_docstring,
        }
        if name is not None:
            kwargs["name"] = name
        if description is not None:
            kwargs["description"] = description
        if args_schema is not None:
            kwargs["args_schema"] = args_schema

        if asyncio.iscoroutinefunction(fn):
            structured_tool = StructuredTool.from_function(func=None, coroutine=fn, **kwargs)
        else:
            structured_tool = StructuredTool.from_function(func=fn, **kwargs)

        # Preserve the original function reference for introspection
        functools.update_wrapper(structured_tool, fn)

        if register:
            from pyworkflow_agents.tools.registry import get_global_registry

            get_global_registry().register(structured_tool)

        return structured_tool

    # Support both @tool and @tool(...) syntax
    if func is not None:
        return decorator(func)
    return decorator
