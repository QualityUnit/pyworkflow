"""
Tool-calling agent loop for pyworkflow agents.

Uses model.bind_tools() and checks response.tool_calls to decide whether
to execute tools or return the final answer.

Supports three execution modes (auto-detected):
- Standalone: No workflow context — always execute LLM + tools directly
- Transient: Context exists, is_durable=False — execute directly, record events
- Durable: Context exists, is_durable=True — LLM cache replay, tool calls as steps
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from pyworkflow_agents.agent.types import AgentResult
from pyworkflow_agents.token_tracking import TokenUsage, TokenUsageTracker
from pyworkflow_agents.tools.base import ToolResult
from pyworkflow_agents.tools.registry import ToolRegistry

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. You have access to tools that you can use "
    "to answer questions and complete tasks.\n\n"
    "When working on a task:\n"
    "1. Think about what information you need and which tools can help\n"
    "2. Use the available tools to gather information or take action\n"
    "3. Analyze the results and decide if you need more information\n"
    "4. Provide a clear, complete answer when you have enough information\n\n"
    "If no tools are needed, respond directly."
)


async def run_tool_calling_loop(
    model: BaseChatModel,
    input: str | list,  # noqa: A002
    tools: list | ToolRegistry | None = None,
    system_prompt: str | None = None,
    max_iterations: int = 10,
    agent_id: str = "",
    agent_name: str = "",
    record_events: bool = True,
    run_id: str | None = None,
) -> AgentResult:
    """Run a tool-calling agent loop: LLM responds, optionally calls tools, repeats until done.

    In durable mode (workflow context with storage), LLM responses are cached for
    deterministic replay and tool calls are recorded as workflow steps.
    """

    # Detect workflow context and execution mode
    ctx, is_durable, run_id = _detect_context(run_id)

    # Deterministic agent_id in durable mode (stable across replays)
    if not agent_id:
        if is_durable:
            input_text = input if isinstance(input, str) else str(input)
            agent_id = _deterministic_agent_id(agent_name or "agent", input_text)
        else:
            agent_id = f"agent_{uuid.uuid4().hex[:12]}"

    registry = _resolve_tools(tools)
    model_name = _get_model_name(model)

    # Build initial messages
    effective_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    messages: list[Any] = []
    messages.append(SystemMessage(content=effective_prompt))
    if isinstance(input, str):
        messages.append(HumanMessage(content=input))
    else:
        messages.extend(input)

    # Token tracking
    tracker = TokenUsageTracker()
    total_usage = TokenUsage()
    tool_calls_count = 0

    # Bind tools to model
    bound_model = model.bind_tools(registry.get_all()) if len(registry) > 0 else model

    # Record AGENT_STARTED event
    if record_events:
        await _record_event(
            run_id,
            _import_create_agent_started_event(),
            agent_id=agent_id,
            agent_name=agent_name,
            model=model_name,
            tools=registry.get_names(),
            system_prompt=effective_prompt,
            input_text=input if isinstance(input, str) else str(input),
        )

    last_response = None

    for iteration in range(max_iterations):
        # =================================================================
        # LLM Call — durable mode checks cache first
        # =================================================================
        if is_durable and ctx is not None:
            cached_llm = ctx.get_cached_agent_llm_response(agent_id, iteration)
            if cached_llm is not None:
                # Replay from cache — skip LLM call entirely
                response = _reconstruct_ai_message(cached_llm)
                iteration_usage = _reconstruct_token_usage(cached_llm)
            else:
                # Fresh LLM call — record and cache
                if record_events:
                    await _record_event(
                        run_id,
                        _import_create_agent_llm_call_event(),
                        agent_id=agent_id,
                        iteration=iteration,
                        messages=[_serialize_message(m) for m in messages],
                        model=model_name,
                        tools=registry.get_names(),
                    )

                response = await bound_model.ainvoke(messages, config={"callbacks": [tracker]})
                iteration_usage = TokenUsage.from_message(response)

                # Extract response data
                response_content = response.content if hasattr(response, "content") else str(response)
                response_tool_calls = getattr(response, "tool_calls", None) or []

                # Record AGENT_LLM_RESPONSE event to storage (critical for replay)
                llm_response_data = {
                    "response_content": response_content,
                    "tool_calls": response_tool_calls if response_tool_calls else None,
                    "token_usage": iteration_usage.to_dict(),
                    "model": model_name,
                }
                create_fn = _import_create_agent_llm_response_event()
                if create_fn and ctx.storage:
                    event = create_fn(
                        run_id=run_id,
                        agent_id=agent_id,
                        iteration=iteration,
                        response_content=response_content,
                        tool_calls=response_tool_calls if response_tool_calls else None,
                        token_usage=iteration_usage.to_dict(),
                        model=model_name,
                    )
                    await ctx.storage.record_event(event)

                # Cache in context for future replays
                ctx.cache_agent_llm_response(agent_id, iteration, llm_response_data)
        else:
            # Non-durable path (standalone or transient)
            if record_events:
                await _record_event(
                    run_id,
                    _import_create_agent_llm_call_event(),
                    agent_id=agent_id,
                    iteration=iteration,
                    messages=[_serialize_message(m) for m in messages],
                    model=model_name,
                    tools=registry.get_names(),
                )

            response = await bound_model.ainvoke(messages, config={"callbacks": [tracker]})
            iteration_usage = TokenUsage.from_message(response)

            response_tool_calls = getattr(response, "tool_calls", None) or []
            if record_events:
                await _record_event(
                    run_id,
                    _import_create_agent_llm_response_event(),
                    agent_id=agent_id,
                    iteration=iteration,
                    response_content=response.content if hasattr(response, "content") else str(response),
                    tool_calls=response_tool_calls if response_tool_calls else None,
                    token_usage=iteration_usage.to_dict(),
                    model=model_name,
                )

        total_usage += iteration_usage

        # =================================================================
        # Process response — tool calls or final answer
        # =================================================================
        response_tool_calls = getattr(response, "tool_calls", None) or []

        if response_tool_calls:
            # Append AI message (with tool_calls) BEFORE ToolMessages
            messages.append(response)

            for tc in response_tool_calls:
                tc_name = tc["name"]
                tc_args = tc["args"]
                tc_id = tc["id"]

                if is_durable and ctx is not None:
                    # Durable mode: execute as step with caching
                    tool_result = await _execute_tool_as_step(
                        ctx, registry, agent_id, iteration,
                        tc_name, tc_args, tc_id, run_id,
                    )
                else:
                    # Non-durable: execute directly
                    if record_events:
                        await _record_event(
                            run_id,
                            _import_create_agent_tool_call_event(),
                            agent_id=agent_id,
                            iteration=iteration,
                            tool_call_id=tc_id,
                            tool_name=tc_name,
                            tool_args=tc_args,
                        )

                    tool_result = await registry.execute(tc_name, tc_args, tc_id)

                    if record_events:
                        await _record_event(
                            run_id,
                            _import_create_agent_tool_result_event(),
                            agent_id=agent_id,
                            iteration=iteration,
                            tool_call_id=tc_id,
                            tool_name=tc_name,
                            result=str(tool_result.result) if not tool_result.is_error else tool_result.error,
                            is_error=tool_result.is_error,
                            duration_ms=tool_result.duration_ms,
                        )

                # Build ToolMessage
                if tool_result.is_error:
                    content = f"Error: {tool_result.error}"
                else:
                    content = str(tool_result.result)
                messages.append(ToolMessage(content=content, tool_call_id=tc_id))
                tool_calls_count += 1

            # Continue loop for next LLM call
            last_response = response
            continue

        # No tool calls — final response
        if record_events:
            await _record_event(
                run_id,
                _import_create_agent_response_event(),
                agent_id=agent_id,
                iteration=iteration,
                content=response.content if hasattr(response, "content") else str(response),
            )

        messages.append(response)

        if record_events:
            await _record_event(
                run_id,
                _import_create_agent_completed_event(),
                agent_id=agent_id,
                result_content=response.content if hasattr(response, "content") else str(response),
                total_iterations=iteration + 1,
                total_tool_calls=tool_calls_count,
                token_usage=total_usage.to_dict(),
                finish_reason="stop",
            )

        return AgentResult(
            content=response.content if hasattr(response, "content") else str(response),
            messages=messages,
            tool_calls_made=tool_calls_count,
            token_usage=total_usage,
            iterations=iteration + 1,
            finish_reason="stop",
            agent_id=agent_id,
        )

    # Max iterations reached
    final_content = ""
    if last_response and hasattr(last_response, "content"):
        final_content = last_response.content

    if record_events:
        await _record_event(
            run_id,
            _import_create_agent_completed_event(),
            agent_id=agent_id,
            result_content=final_content,
            total_iterations=max_iterations,
            total_tool_calls=tool_calls_count,
            token_usage=total_usage.to_dict(),
            finish_reason="max_iterations",
        )

    return AgentResult(
        content=final_content,
        messages=messages,
        tool_calls_made=tool_calls_count,
        token_usage=total_usage,
        iterations=max_iterations,
        finish_reason="max_iterations",
        agent_id=agent_id,
    )


# ---------------------------------------------------------------------------
# Context detection and durable mode helpers
# ---------------------------------------------------------------------------


def _detect_context(run_id: str | None) -> tuple[Any, bool, str | None]:
    """Detect workflow context and determine execution mode.

    Returns:
        (ctx, is_durable, effective_run_id) where:
        - ctx: WorkflowContext or None (standalone)
        - is_durable: True if durable mode with storage
        - effective_run_id: run_id from arg or context
    """
    try:
        from pyworkflow.context import get_context, has_context

        if has_context():
            ctx = get_context()
            effective_run_id = run_id or ctx.run_id
            return ctx, ctx.is_durable, effective_run_id
    except ImportError:
        pass
    return None, False, run_id


def _deterministic_agent_id(agent_name: str, input_text: str) -> str:
    """Generate deterministic agent_id from name + input hash.

    Stable across replays for the same agent invocation.
    """
    content = f"{agent_name}:{input_text}"
    hash_hex = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"agent_{hash_hex}"


def _reconstruct_ai_message(cached_data: dict[str, Any]) -> AIMessage:
    """Reconstruct an AIMessage from cached LLM response data."""
    content = cached_data.get("response_content", "")
    tool_calls = cached_data.get("tool_calls") or []
    return AIMessage(content=content, tool_calls=tool_calls)


def _reconstruct_token_usage(cached_data: dict[str, Any]) -> TokenUsage:
    """Reconstruct TokenUsage from cached data."""
    token_usage = cached_data.get("token_usage")
    if token_usage:
        return TokenUsage(
            input_tokens=token_usage.get("input_tokens", 0),
            output_tokens=token_usage.get("output_tokens", 0),
            total_tokens=token_usage.get("total_tokens", 0),
        )
    return TokenUsage()


async def _execute_tool_as_step(
    ctx: Any,
    registry: ToolRegistry,
    agent_id: str,
    iteration: int,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_call_id: str,
    run_id: str | None,
) -> ToolResult:
    """Execute a tool call as a durable step with caching.

    1. Check agent tool cache — return cached result if available
    2. Record STEP_STARTED event
    3. Execute tool via registry
    4. Record STEP_COMPLETED or STEP_FAILED event
    5. Cache result in context
    6. Record AGENT_TOOL_RESULT event
    """
    from pyworkflow.engine.events import (
        create_agent_tool_call_event,
        create_agent_tool_result_event,
        create_step_completed_event,
        create_step_failed_event,
        create_step_started_event,
    )
    from pyworkflow.serialization.encoder import serialize

    step_id = f"agent_tool_{agent_id}_{iteration}_{tool_call_id}"

    # Check cache first
    cached = ctx.get_cached_agent_tool_result(agent_id, iteration, tool_call_id)
    if cached is not None:
        # Reconstruct ToolResult from cache
        is_error = cached.get("is_error", False)
        result_value = cached["result"]
        return ToolResult(
            tool_name=cached.get("tool_name", tool_name),
            tool_call_id=tool_call_id,
            result=None if is_error else result_value,
            error=result_value if is_error else None,
            duration_ms=cached.get("duration_ms", 0),
            is_error=is_error,
        )

    # Record AGENT_TOOL_CALL event
    if ctx.storage:
        tool_call_event = create_agent_tool_call_event(
            run_id=run_id,
            agent_id=agent_id,
            iteration=iteration,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        await ctx.storage.record_event(tool_call_event)

    # Record STEP_STARTED event
    started_event = create_step_started_event(
        run_id=run_id,
        step_id=step_id,
        step_name=f"agent_tool:{tool_name}",
        args=str(tool_args),
        kwargs="",
        attempt=1,
    )
    await ctx.storage.record_event(started_event)

    # Execute tool
    tool_result = await registry.execute(tool_name, tool_args, tool_call_id)

    # Determine result string (matches non-durable event recording)
    result_str = str(tool_result.result) if not tool_result.is_error else tool_result.error

    # Record STEP_COMPLETED or STEP_FAILED
    if tool_result.is_error:
        failed_event = create_step_failed_event(
            run_id=run_id,
            step_id=step_id,
            error=tool_result.error or "Unknown error",
            error_type="ToolExecutionError",
            is_retryable=False,
            attempt=1,
        )
        await ctx.storage.record_event(failed_event)
    else:
        completed_event = create_step_completed_event(
            run_id=run_id,
            step_id=step_id,
            result=serialize(result_str),
            step_name=f"agent_tool:{tool_name}",
        )
        await ctx.storage.record_event(completed_event)

    # Cache in step_results
    ctx.cache_step_result(step_id, result_str)

    # Cache agent tool result (enriched dict)
    ctx.cache_agent_tool_result(
        agent_id, iteration, tool_call_id, result_str,
        is_error=tool_result.is_error,
        tool_name=tool_name,
        duration_ms=tool_result.duration_ms,
    )

    # Record AGENT_TOOL_RESULT event
    tool_result_event = create_agent_tool_result_event(
        run_id=run_id,
        agent_id=agent_id,
        iteration=iteration,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        result=result_str,
        is_error=tool_result.is_error,
        duration_ms=tool_result.duration_ms,
    )
    await ctx.storage.record_event(tool_result_event)

    return tool_result


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------


def _resolve_tools(tools: list | ToolRegistry | None) -> ToolRegistry:
    """Convert a list of BaseTool or a ToolRegistry to a ToolRegistry."""
    if tools is None:
        return ToolRegistry()
    if isinstance(tools, ToolRegistry):
        return tools
    # Assume list of BaseTool
    registry = ToolRegistry()
    for t in tools:
        if isinstance(t, BaseTool):
            registry.register(t)
    return registry


def _get_model_name(model: BaseChatModel) -> str:
    """Extract the model name from a BaseChatModel."""
    for attr in ("model_name", "model"):
        val = getattr(model, attr, None)
        if val and isinstance(val, str):
            return val
    return type(model).__name__


def _serialize_message(msg: Any) -> dict[str, Any]:
    """Serialize a langchain message to a dict for event recording."""
    if hasattr(msg, "model_dump"):
        return msg.model_dump()
    if hasattr(msg, "dict"):
        return msg.dict()
    return {"content": str(msg), "type": type(msg).__name__}


async def _record_event(run_id: str | None, create_func: Any, **kwargs: Any) -> None:
    """Best-effort event recording — does not break the agent loop on failure."""
    if not run_id or create_func is None:
        return
    try:
        from pyworkflow.context import get_context

        ctx = get_context()
        if ctx and hasattr(ctx, "storage") and ctx.storage:
            event = create_func(run_id=run_id, **kwargs)
            await ctx.storage.record_event(event)
    except Exception:
        pass  # Best-effort


# ---------------------------------------------------------------------------
# Lazy imports for event creation helpers (avoid hard dependency on pyworkflow.engine)
# ---------------------------------------------------------------------------


def _import_create_agent_started_event() -> Any:
    try:
        from pyworkflow.engine.events import create_agent_started_event
        return create_agent_started_event
    except ImportError:
        return None


def _import_create_agent_llm_call_event() -> Any:
    try:
        from pyworkflow.engine.events import create_agent_llm_call_event
        return create_agent_llm_call_event
    except ImportError:
        return None


def _import_create_agent_llm_response_event() -> Any:
    try:
        from pyworkflow.engine.events import create_agent_llm_response_event
        return create_agent_llm_response_event
    except ImportError:
        return None


def _import_create_agent_tool_call_event() -> Any:
    try:
        from pyworkflow.engine.events import create_agent_tool_call_event
        return create_agent_tool_call_event
    except ImportError:
        return None


def _import_create_agent_tool_result_event() -> Any:
    try:
        from pyworkflow.engine.events import create_agent_tool_result_event
        return create_agent_tool_result_event
    except ImportError:
        return None


def _import_create_agent_response_event() -> Any:
    try:
        from pyworkflow.engine.events import create_agent_response_event
        return create_agent_response_event
    except ImportError:
        return None


def _import_create_agent_completed_event() -> Any:
    try:
        from pyworkflow.engine.events import create_agent_completed_event
        return create_agent_completed_event
    except ImportError:
        return None
