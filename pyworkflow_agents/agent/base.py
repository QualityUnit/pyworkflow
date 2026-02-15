"""
Agent base class (OOP API) for pyworkflow agents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from pyworkflow_agents.agent.tool_calling.loop import run_tool_calling_loop
from pyworkflow_agents.agent.types import AgentResult
from pyworkflow_agents.tools.registry import ToolRegistry


class Agent(ABC):
    """
    Abstract base class for agents.

    Subclasses must implement ``run()`` to produce the initial prompt or message list.
    The class docstring is used as the system prompt if none is explicitly set.
    """

    model: BaseChatModel | None = None
    tools: list | ToolRegistry | None = None
    system_prompt: str | None = None
    max_iterations: int = 10
    name: str | None = None
    record_events: bool = True
    parallel_tool_calls: bool = True
    require_approval: bool | list[str] | Callable[[str, dict], bool] | None = None
    approval_handler: Callable[[list[dict]], Awaitable[list[dict]]] | None = None
    on_agent_action: Callable | None = None

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> str | list:
        """Return the initial prompt for the agent loop. Must be implemented by subclasses."""
        ...

    async def __call__(self, *args: Any, _model: BaseChatModel | None = None, **kwargs: Any) -> AgentResult:
        actual_model = _model or self.model
        if actual_model is None:
            raise ValueError(
                f"Agent '{self._get_name()}' has no model. "
                f"Pass model= to the class or _model= at call time."
            )

        actual_system_prompt = self.system_prompt
        if actual_system_prompt is None:
            actual_system_prompt = self.__class__.__doc__

        input_prompt = await self.run(*args, **kwargs)

        # Detect workflow context for run_id
        run_id = None
        try:
            from pyworkflow.context import get_context, has_context

            if has_context():
                run_id = get_context().run_id
        except ImportError:
            pass

        return await run_tool_calling_loop(
            model=actual_model,
            input=input_prompt,
            tools=self.tools,
            system_prompt=actual_system_prompt,
            max_iterations=self.max_iterations,
            agent_id=f"agent_{self._get_name()}",
            agent_name=self._get_name(),
            record_events=self.record_events,
            run_id=run_id,
            parallel_tool_calls=self.parallel_tool_calls,
            require_approval=self.require_approval,
            approval_handler=self.approval_handler,
            on_agent_action=self.on_agent_action,
        )

    def _get_name(self) -> str:
        return self.name or type(self).__name__
