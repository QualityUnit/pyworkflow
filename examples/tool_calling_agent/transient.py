"""
Tool-Calling Agent — Transient Runtime

Run an agent inside a transient (non-durable) pyworkflow workflow.
Events are recorded in-process but there is no storage backend,
so there is no crash recovery or replay.

This is useful when you want workflow orchestration (steps, retries)
around your agent call but don't need persistence.

Three styles are shown:
  1. @tool_calling_agent inside a @workflow
  2. Agent base class inside a @workflow
  3. run_tool_calling_loop() inside a @step

Requirements:
    pip install 'pyworkflow-engine[agents]' langchain-openai

Run:
    OPENAI_API_KEY=sk-... python examples/tool_calling_agent/transient.py
"""

import asyncio
import os

from langchain_openai import ChatOpenAI

from pyworkflow import configure, reset_config, start, step, workflow
from pyworkflow_agents import Agent, tool, tool_calling_agent
from pyworkflow_agents.agent.tool_calling.loop import run_tool_calling_loop

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(register=False)
def lookup_order(order_id: str) -> str:
    """Look up an order by ID."""
    orders = {
        "ORD-001": "Widget x3, shipped, delivery ETA 2 days",
        "ORD-002": "Gadget x1, processing, payment confirmed",
    }
    return orders.get(order_id, f"Order {order_id} not found")


@tool(register=False)
def check_inventory(product: str) -> str:
    """Check inventory for a product."""
    stock = {"widget": "142 in stock", "gadget": "7 in stock"}
    return stock.get(product.lower(), f"No inventory data for {product}")


TOOLS = [lookup_order, check_inventory]
model = ChatOpenAI(model="gpt-4o-mini")


# ---------------------------------------------------------------------------
# 1. Decorator agent inside a workflow
# ---------------------------------------------------------------------------


@tool_calling_agent(model=model, tools=TOOLS)
async def support_agent(query: str):
    """You are a customer-support agent. Use tools to look up orders and inventory."""
    return query


@workflow(durable=False)
async def support_workflow_decorator(query: str) -> dict:
    """Handle a support query using the decorator-style agent."""
    result = await support_agent(query)
    return {"answer": result.content, "tool_calls": result.tool_calls_made}


# ---------------------------------------------------------------------------
# 2. Base-class agent inside a workflow
# ---------------------------------------------------------------------------


class SupportAgent(Agent):
    """You are a customer-support agent. Use tools to look up orders and inventory."""

    model = model
    tools = TOOLS

    async def run(self, query: str) -> str:
        return query


@workflow(durable=False)
async def support_workflow_class(query: str) -> dict:
    """Handle a support query using the base-class agent."""
    agent = SupportAgent()
    result = await agent(query=query)
    return {"answer": result.content, "tool_calls": result.tool_calls_made}


# ---------------------------------------------------------------------------
# 3. Direct loop inside a step
# ---------------------------------------------------------------------------


@step()
async def agent_step(query: str) -> dict:
    """Run the agent loop directly inside a step."""
    result = await run_tool_calling_loop(
        model=model,
        input=query,
        tools=TOOLS,
        system_prompt="You are a customer-support agent. Use tools to look up orders and inventory.",
    )
    return {"answer": result.content, "tool_calls": result.tool_calls_made}


@workflow(durable=False)
async def support_workflow_direct(query: str) -> dict:
    """Handle a support query using run_tool_calling_loop inside a step."""
    return await agent_step(query)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this example.")
        return

    reset_config()
    configure(default_durable=False)

    query = "What's the status of order ORD-001? Also, how many widgets are in stock?"

    print("=== Tool-Calling Agent — Transient Runtime ===\n")

    # 1. Decorator
    print("--- 1. @tool_calling_agent inside @workflow ---")
    run_id = await start(support_workflow_decorator, query)
    print(f"  run_id: {run_id}\n")

    # 2. Base class
    print("--- 2. Agent base class inside @workflow ---")
    run_id = await start(support_workflow_class, query)
    print(f"  run_id: {run_id}\n")

    # 3. Direct loop
    print("--- 3. run_tool_calling_loop() inside @step ---")
    run_id = await start(support_workflow_direct, query)
    print(f"  run_id: {run_id}\n")

    print("=== Key Characteristics ===")
    print("  - Workflow context exists but is_durable=False")
    print("  - Events recorded in-process (no storage backend)")
    print("  - No crash recovery — state lost on process exit")
    print("  - Useful for orchestrating agents with steps and retries")


if __name__ == "__main__":
    asyncio.run(main())
