"""
Tool-Calling Agent — Durable Runtime

Run an agent inside a durable (event-sourced) pyworkflow workflow.
LLM responses and tool results are cached as events in storage,
so the agent can be replayed deterministically after a crash.

This is the most robust mode — every LLM call and tool execution is
recorded and can be inspected via the event log.

Three styles are shown:
  1. @tool_calling_agent inside a durable @workflow
  2. Agent base class inside a durable @workflow
  3. run_tool_calling_loop() inside a durable @step

Requirements:
    pip install 'pyworkflow-engine[agents]' langchain-openai

Run:
    OPENAI_API_KEY=sk-... python examples/tool_calling_agent/durable.py
"""

import asyncio
import os

from langchain_openai import ChatOpenAI

from pyworkflow import (
    configure,
    get_workflow_events,
    get_workflow_run,
    reset_config,
    start,
    step,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend
from pyworkflow_agents import Agent, tool, tool_calling_agent
from pyworkflow_agents.agent.tool_calling.loop import run_tool_calling_loop

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(register=False)
def search_docs(query: str) -> str:
    """Search the documentation for relevant articles."""
    docs = {
        "billing": "Billing FAQ: Invoices are sent on the 1st. Refunds take 5-7 days.",
        "shipping": "Shipping Policy: Free over $50. Standard 3-5 days, Express 1-2 days.",
        "returns": "Return Policy: 30-day window. Items must be unused. Free return label.",
    }
    for key, content in docs.items():
        if key in query.lower():
            return content
    return "No relevant documentation found."


@tool(register=False)
def create_ticket(subject: str, priority: str) -> str:
    """Create a support ticket."""
    return f"Ticket created — subject: '{subject}', priority: {priority}, id: TKT-42"


TOOLS = [search_docs, create_ticket]
model = ChatOpenAI(model="gpt-4o-mini")


# ---------------------------------------------------------------------------
# 1. Decorator agent inside a durable workflow
# ---------------------------------------------------------------------------


@tool_calling_agent(model=model, tools=TOOLS)
async def helpdesk_agent(query: str):
    """You are a helpdesk agent. Search docs first, then create a ticket if needed."""
    return query


@workflow(durable=True)
async def helpdesk_workflow_decorator(query: str) -> dict:
    """Handle a helpdesk query using the decorator-style agent."""
    result = await helpdesk_agent(query)
    return {"answer": result.content, "tool_calls": result.tool_calls_made}


# ---------------------------------------------------------------------------
# 2. Base-class agent inside a durable workflow
# ---------------------------------------------------------------------------


class HelpdeskAgent(Agent):
    """You are a helpdesk agent. Search docs first, then create a ticket if needed."""

    model = model
    tools = TOOLS

    async def run(self, query: str) -> str:
        return query


@workflow(durable=True)
async def helpdesk_workflow_class(query: str) -> dict:
    """Handle a helpdesk query using the base-class agent."""
    agent = HelpdeskAgent()
    result = await agent(query=query)
    return {"answer": result.content, "tool_calls": result.tool_calls_made}


# ---------------------------------------------------------------------------
# 3. Direct loop inside a durable step
# ---------------------------------------------------------------------------


@step()
async def agent_step(query: str) -> dict:
    """Run the agent loop directly inside a durable step."""
    result = await run_tool_calling_loop(
        model=model,
        input=query,
        tools=TOOLS,
        system_prompt="You are a helpdesk agent. Search docs first, then create a ticket if needed.",
    )
    return {"answer": result.content, "tool_calls": result.tool_calls_made}


@workflow(durable=True)
async def helpdesk_workflow_direct(query: str) -> dict:
    """Handle a helpdesk query using run_tool_calling_loop inside a step."""
    return await agent_step(query)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def print_event_log(run_id: str):
    """Print the event log for a workflow run."""
    events = await get_workflow_events(run_id)
    print(f"\n  Event log ({len(events)} events):")
    for event in events:
        etype = event.type.value
        detail = ""
        if etype == "agent_llm_response":
            content = event.data.get("response_content", "")[:60]
            detail = f" — {content}..."
        elif etype == "agent_tool_call":
            detail = f" — {event.data.get('tool_name', '?')}({event.data.get('tool_args', '')})"
        elif etype == "agent_tool_result":
            result = str(event.data.get("result", ""))[:60]
            detail = f" — {result}"
        print(f"    {event.sequence:>3}: {etype}{detail}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this example.")
        return

    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    query = "I need to return an item I bought last week. Can you help and create a ticket?"

    print("=== Tool-Calling Agent — Durable Runtime ===\n")

    # 1. Decorator
    print("--- 1. @tool_calling_agent inside durable @workflow ---")
    run_id = await start(helpdesk_workflow_decorator, query)
    run = await get_workflow_run(run_id)
    print(f"  run_id: {run_id}")
    print(f"  status: {run.status.value}")
    await print_event_log(run_id)

    # 2. Base class
    print("\n--- 2. Agent base class inside durable @workflow ---")
    run_id = await start(helpdesk_workflow_class, query)
    run = await get_workflow_run(run_id)
    print(f"  run_id: {run_id}")
    print(f"  status: {run.status.value}")
    await print_event_log(run_id)

    # 3. Direct loop
    print("\n--- 3. run_tool_calling_loop() inside durable @step ---")
    run_id = await start(helpdesk_workflow_direct, query)
    run = await get_workflow_run(run_id)
    print(f"  run_id: {run_id}")
    print(f"  status: {run.status.value}")
    await print_event_log(run_id)

    print("\n=== Key Characteristics ===")
    print("  - Workflow context exists with is_durable=True")
    print("  - LLM responses cached as AGENT_LLM_RESPONSE events")
    print("  - Tool calls recorded as steps (STEP_STARTED / STEP_COMPLETED)")
    print("  - On replay: cached LLM responses returned without calling the API")
    print("  - Full event log available for debugging and auditing")


if __name__ == "__main__":
    asyncio.run(main())
