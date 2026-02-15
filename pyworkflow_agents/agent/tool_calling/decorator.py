"""
@tool_calling_agent decorator for defining tool-calling agents as decorated functions.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from pyworkflow_agents.agent.tool_calling.loop import run_tool_calling_loop
from pyworkflow_agents.agent.types import AgentResult
from pyworkflow_agents.tools.registry import ToolRegistry


def tool_calling_agent(
    func: Callable | None = None,
    *,
    model: BaseChatModel | None = None,
    tools: list | ToolRegistry | None = None,
    system_prompt: str | None = None,
    max_iterations: int = 10,
    name: str | None = None,
    record_events: bool = True,
    parallel_tool_calls: bool = True,
    require_approval: bool | list[str] | Callable[[str, dict], bool] | None = None,
    approval_handler: Callable[[list[dict]], Awaitable[list[dict]]] | None = None,
    on_agent_action: Callable | None = None,
) -> Any:
    """
    Decorator to turn a function into a tool-calling agent.

    The decorated function should return a string (prompt) or list of messages.
    The agent loop will then run with the provided model and tools.

    Supports both ``@tool_calling_agent`` and ``@tool_calling_agent(model=..., tools=...)`` syntax.
    """

    def decorator(fn: Callable) -> Callable[..., Any]:
        actual_name = name or fn.__name__
        actual_system_prompt = system_prompt
        if actual_system_prompt is None:
            actual_system_prompt = fn.__doc__

        @functools.wraps(fn)
        async def wrapper(*args: Any, _model: BaseChatModel | None = None, **kwargs: Any) -> AgentResult:
            resolved_model = _model or model
            if resolved_model is None:
                raise ValueError(
                    f"Agent '{actual_name}' has no model. "
                    f"Pass model= to the decorator or _model= at call time."
                )

            # Call the decorated function to get the input prompt
            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            input_prompt = result

            # Detect workflow context for run_id
            run_id = None
            try:
                from pyworkflow.context import get_context, has_context

                if has_context():
                    run_id = get_context().run_id
            except ImportError:
                pass

            return await run_tool_calling_loop(
                model=resolved_model,
                input=input_prompt,
                tools=tools,
                system_prompt=actual_system_prompt,
                max_iterations=max_iterations,
                agent_id=f"agent_{actual_name}",
                agent_name=actual_name,
                record_events=record_events,
                run_id=run_id,
                parallel_tool_calls=parallel_tool_calls,
                require_approval=require_approval,
                approval_handler=approval_handler,
                on_agent_action=on_agent_action,
            )

        wrapper.__agent__ = True  # type: ignore[attr-defined]
        wrapper.__agent_name__ = actual_name  # type: ignore[attr-defined]
        wrapper.__agent_model__ = model  # type: ignore[attr-defined]
        wrapper.__agent_tools__ = tools  # type: ignore[attr-defined]
        wrapper.__agent_system_prompt__ = actual_system_prompt  # type: ignore[attr-defined]
        wrapper.__agent_max_iterations__ = max_iterations  # type: ignore[attr-defined]

        return wrapper

    # Support both @tool_calling_agent and @tool_calling_agent(...) syntax
    if func is not None:
        return decorator(func)
    return decorator
